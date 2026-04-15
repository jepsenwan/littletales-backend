import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from celery import shared_task
from django.db import close_old_connections
from .models import Story, StoryPage, StoryAudio, GenerationJob, ChildProfile

logger = logging.getLogger(__name__)

# Post-text phases in the MAIN pipeline: images + audio + quiz = 3 phases.
# Coloring pages and vocab illustrations are deferred to a background task
# (they aren't needed for playback — user can open the story immediately).
# Starting point (after text): 20%. Each phase completion: +25%.
_PHASE_PROGRESS_START = 20
_PHASE_PROGRESS_PER = 25


def _run_phase(name, func, on_done, *args):
    """Run a pipeline phase in a worker thread.

    Calls on_done() when the phase finishes so the parent can bump
    progress atomically, regardless of which phase finished first.
    Closes the thread-local DB connection afterwards so Django doesn't
    leak connections from the Celery worker process.
    """
    try:
        func(*args)
    except Exception as e:
        logger.exception(f"Phase {name} failed: {e}")
        raise
    finally:
        try:
            on_done(name)
        except Exception:
            pass
        close_old_connections()


@shared_task(bind=True, max_retries=1)
def run_story_generation_pipeline(self, job_id, params):
    """
    Main pipeline: text first, then images/coloring/audio/quiz/vocab in parallel.
    All post-text phases only depend on the story text/pages, so they can run
    concurrently. Network IO bound (external APIs + R2), so threads give a
    real speedup.
    """
    try:
        job = GenerationJob.objects.get(id=job_id)
        story = job.story

        # Phase 1: Generate story text (must finish first — all downstream
        # phases read the pages it creates).
        _generate_text(job, story, params)

        # Phases 2-5 run concurrently.
        job.status = 'generating_assets'
        job.progress = _PHASE_PROGRESS_START
        job.save(update_fields=['status', 'progress'])

        # Only playback-critical phases in the main pipeline. Coloring and
        # vocab illustrations are fired off as a deferred task below.
        phases = [
            ('images', _generate_images, job, story),
            ('audio', _generate_audio, job, story),
            ('quiz', _generate_quiz, job, story),
        ]

        # Monotonic progress: single writer, never decreases. Per-phase code
        # does NOT save progress itself anymore — that's what caused the
        # "90% drops back to 40%" race.
        progress_lock = threading.Lock()
        completed_count = {'n': 0}

        def on_phase_done(phase_name):
            with progress_lock:
                completed_count['n'] += 1
                new_progress = _PHASE_PROGRESS_START + completed_count['n'] * _PHASE_PROGRESS_PER
                # Fetch fresh to avoid overwriting unrelated fields.
                GenerationJob.objects.filter(id=job.id).update(progress=new_progress)

        # Per-phase watchdog: any phase that hasn't finished in PHASE_TIMEOUT
        # seconds has its future cancelled so the whole story doesn't hang
        # forever when an upstream image/audio API stalls.
        PHASE_TIMEOUT = 600  # 10 minutes per phase; the whole story should
                             # normally finish well under this budget.

        failures = []
        with ThreadPoolExecutor(max_workers=len(phases)) as executor:
            future_to_name = {
                executor.submit(_run_phase, name, func, on_phase_done, *rest): name
                for (name, func, *rest) in phases
            }
            try:
                for future in as_completed(future_to_name, timeout=PHASE_TIMEOUT):
                    name = future_to_name[future]
                    exc = future.exception()
                    if exc is not None:
                        failures.append((name, exc))
            except TimeoutError:
                # Record any phase that didn't finish as a failure.
                for future, name in future_to_name.items():
                    if not future.done():
                        failures.append((name, TimeoutError(f'{name} exceeded {PHASE_TIMEOUT}s')))
                        future.cancel()

        # Images must succeed — it's the core deliverable. Other phases
        # (quiz, vocab illustrations, coloring) are enhancements.
        critical_failed = any(n == 'images' or n == 'audio' for n, _ in failures)
        if critical_failed:
            raise RuntimeError(f"Critical phase(s) failed: {[(n, str(e)) for n, e in failures]}")

        # Main pipeline done — user can open + play the story now.
        story.status = 'completed'
        story.save()
        job.status = 'completed'
        job.progress = 100
        job.save()
        logger.info(f"Story generation completed: job={job_id}, story={story.id}")

        # Kick off deferred assets (coloring pages + vocab illustrations).
        # Fire-and-forget: failures here don't roll back the main story.
        try:
            run_deferred_assets.delay(story.id)
        except Exception as e:
            logger.warning(f"Failed to dispatch deferred assets for story {story.id}: {e}")

    except Exception as e:
        logger.error(f"Story generation failed: job={job_id}, error={e}")
        try:
            job = GenerationJob.objects.get(id=job_id)
            job.status = 'failed'
            job.error_message = str(e)
            job.save()
            used_bonus = False
            if job.story:
                job.story.status = 'failed'
                job.story.save()
                used_bonus = bool(job.story.generation_params.get('_quota_used_bonus', False))
            # Refund the user's quota credit so they don't lose it on a server error
            from .services.quota import refund_quota
            refund_quota(job.user, used_bonus=used_bonus)
        except Exception:
            pass
        raise


@shared_task(bind=True, max_retries=1)
def run_deferred_assets(self, story_id):
    """Generate coloring pages + vocab illustrations after the main pipeline.

    These aren't needed to play the story, so they're decoupled: the user
    opens the story as soon as images/audio/quiz are ready, and these
    assets stream in behind the scenes. Frontend reads
    `story.deferred_assets_status` to show "still creating" placeholders.
    """
    try:
        story = Story.objects.get(id=story_id)
    except Story.DoesNotExist:
        logger.warning(f"run_deferred_assets: story {story_id} not found")
        return

    Story.objects.filter(id=story_id).update(deferred_assets_status='running')

    phases = [
        ('coloring', _generate_coloring_pages),
        ('vocab', _generate_vocab_illustrations),
    ]
    failures = []
    # Same bounded concurrency as the main pipeline so they don't serialize.
    with ThreadPoolExecutor(max_workers=len(phases)) as executor:
        future_to_name = {
            executor.submit(_run_phase, name, func, lambda _n: None, None, story): name
            for (name, func) in phases
        }
        try:
            for future in as_completed(future_to_name, timeout=600):
                name = future_to_name[future]
                exc = future.exception()
                if exc is not None:
                    failures.append((name, exc))
        except TimeoutError:
            for future, name in future_to_name.items():
                if not future.done():
                    failures.append((name, TimeoutError(f'{name} exceeded 600s')))
                    future.cancel()

    new_status = 'failed' if failures else 'completed'
    Story.objects.filter(id=story_id).update(deferred_assets_status=new_status)
    if failures:
        logger.error(f"Deferred assets failures for story {story_id}: {[(n, str(e)) for n, e in failures]}")
    else:
        logger.info(f"Deferred assets completed for story {story_id}")


def _generate_text(job, story, params):
    """Phase 1: Generate structured story JSON via LLM."""
    job.status = 'generating_text'
    job.progress = 5
    job.save()

    from .services.story_generation import StoryGenerationService
    service = StoryGenerationService()

    # Auto-link ChildProfile early so character description is available
    child_name = params.get('child_name', '')
    if child_name and not story.child_profile:
        profile, _ = ChildProfile.objects.get_or_create(
            user=story.created_by,
            child_name=child_name,
            defaults={
                'personality': params.get('personality', []),
                'personality_detail': params.get('personality_detail', ''),
            },
        )
        story.child_profile = profile
        story.save()

    # Inject character description if child has a created character
    if story.child_profile and story.child_profile.character_description:
        params['character_description'] = story.child_profile.character_description
        logger.info(f"Injected character description: {story.child_profile.character_description[:60]}")

    # Collect vocab words already taught to this child in recent stories so
    # the generator can avoid repeating flashcards the user has already seen.
    if story.child_profile:
        recent_pages = StoryPage.objects.filter(
            story__child_profile=story.child_profile,
            story__status='completed',
        ).exclude(story=story).order_by('-story__created_at', 'page_number')[:120]
        seen = []
        seen_set = set()
        for page in recent_pages:
            for entry in (page.vocabulary or []):
                w = (entry.get('word') or '').strip()
                if w and w not in seen_set:
                    seen_set.add(w)
                    seen.append(w)
            if len(seen) >= 200:
                break
        if seen:
            params['recent_vocab_words'] = seen[:200]
            logger.info(f"Passing {len(params['recent_vocab_words'])} previously-learned words to avoid")

    story_data = service.generate(params)

    # Update story
    story.title = story_data.get('title', 'Untitled')
    story.moral = story_data.get('moral', '')
    story.goodnight_message = story_data.get('goodnight_message', '')
    story.save()

    # Build character description block for consistency enforcement
    characters = story_data.get('characters', {})
    char_block = ''
    if characters:
        char_block = ' '.join(
            f"{name}: {desc}." for name, desc in characters.items()
        )

    # Create pages, enforcing character descriptions in every image_prompt
    pages = story_data.get('pages', [])
    for page_data in pages:
        image_prompt = page_data.get('image_prompt', '')

        # Auto-inject missing character descriptions
        if image_prompt and char_block:
            prompt_lower = image_prompt.lower()
            missing = [
                f"{name}: {desc}"
                for name, desc in characters.items()
                if name.lower() in prompt_lower and desc.lower()[:30] not in prompt_lower
            ]
            if missing:
                inject = '. '.join(missing) + '. '
                image_prompt = inject + image_prompt
                logger.info(f"Injected character descriptions into page {page_data.get('page_number')} prompt")

        StoryPage.objects.create(
            story=story,
            page_number=page_data.get('page_number', 1),
            text=page_data.get('text', ''),
            image_prompt=image_prompt,
            narration=page_data.get('narration', page_data.get('text', '')),
            dialogue=page_data.get('dialogue', []),
            character_positions=page_data.get('character_positions', []),
            vocabulary=page_data.get('vocabulary', []),
        )

    job.progress = 20
    job.save()
    logger.info(f"Text generated: story={story.id}, pages={len(pages)}")


def _generate_images(job, story):
    """Phase 2: Generate images using 4-panel mode (1 API call per 4 pages)."""
    # Status/progress are set coarsely by the pipeline; per-phase progress
    # updates still happen below (scoped saves to avoid thread stomps).

    from .services.image_generation import ImageGenerationService
    service = ImageGenerationService()

    pages = [p for p in story.pages.all() if p.image_prompt]
    total_pages = len(pages)

    import time as _time
    generated = 0
    api_calls = 0

    # Process pages in batches of 4 for quad-panel generation
    i = 0
    while i < total_pages:
        if i > 0:
            _time.sleep(3)

        remaining = total_pages - i
        batch_size = min(4, remaining)
        batch = pages[i:i + batch_size]

        if batch_size >= 2:
            # Quad/multi-panel: generate 2-4 pages in 1 API call
            page_data = [(p.page_number, p.image_prompt) for p in batch]
            results = service.generate_quad_panel(story.id, page_data, age_group=story.age_group, story_type=story.story_type)
            api_calls += 1

            # Map results back to pages
            result_map = {pn: url for pn, url in results}
            for p in batch:
                if p.page_number in result_map:
                    p.image_url = result_map[p.page_number]
                    p.save(update_fields=['image_url'])
                else:
                    # Fallback: generate individually for failed panels
                    _time.sleep(3)
                    url = service.generate_page_image(story.id, p.page_number, p.image_prompt, age_group=story.age_group, story_type=story.story_type)
                    api_calls += 1
                    if url:
                        p.image_url = url
                        p.save(update_fields=['image_url'])

            generated += batch_size
            i += batch_size
        else:
            # Single remaining page
            page = batch[0]
            url = service.generate_page_image(story.id, page.page_number, page.image_prompt, age_group=story.age_group, story_type=story.story_type)
            api_calls += 1
            if url:
                page.image_url = url
                page.save(update_fields=['image_url'])
            generated += 1
            i += 1

        # Progress is managed by the parent pipeline (phase-completion
        # based) — don't write here, it used to race with other phases.

    logger.info(f"Images generated: story={story.id}, {total_pages} pages in {api_calls} API calls")

    # Phase 2b: Detect character positions in generated images via vision model
    _detect_positions(story)


def _detect_positions(story):
    """Use vision model to find character head positions for speech bubble placement."""
    from .services.character_detection import detect_character_positions

    # Collect all character names from dialogue across pages
    all_names = set()
    for page in story.pages.all():
        for d in (page.dialogue or []):
            if d.get('character'):
                all_names.add(d['character'])

    if not all_names:
        return

    names_list = list(all_names)
    for page in story.pages.filter(image_url__gt=''):
        # Only detect for pages that have dialogue
        page_chars = [d['character'] for d in (page.dialogue or []) if d.get('character')]
        if not page_chars:
            continue
        try:
            positions = detect_character_positions(page.image_url, page_chars)
            if positions:
                page.character_positions = positions
                page.save(update_fields=['character_positions'])
                logger.info(f"Detected positions for story {story.id} page {page.page_number}: {positions}")
        except Exception as e:
            logger.warning(f"Position detection failed for page {page.page_number}: {e}")


def _generate_coloring_pages(job, story):
    """Phase 2c: Generate coloring book line art for each page."""
    from .services.image_generation import ImageGenerationService
    service = ImageGenerationService()

    pages = [(p.page_number, p.image_prompt) for p in story.pages.all() if p.image_prompt]
    if not pages:
        return

    results = service.generate_coloring_pages(story.id, pages, age_group=story.age_group)
    result_map = {pn: url for pn, url in results}

    for page in story.pages.all():
        if page.page_number in result_map:
            page.coloring_image_url = result_map[page.page_number]
            page.save(update_fields=['coloring_image_url'])

    logger.info(f"Coloring pages generated: story={story.id}, {len(results)}/{len(pages)} pages")


def _generate_audio(job, story):
    """Phase 3: Generate narration audio for each page."""

    from .services.audio_generation import AudioGenerationService
    service = AudioGenerationService()

    # Determine voice: from generation_params or default by language
    params = story.generation_params or {}
    voice = params.get('voice')
    if not voice:
        lang = story.language or 'en'
        from django.conf import settings as django_settings
        voices = django_settings.TTS_VOICES.get(lang, django_settings.TTS_VOICES.get('en', []))
        voice = voices[0]['id'] if voices else 'en_female_dacey_uranus_bigtts'

    pages = list(story.pages.all())
    total_pages = len(pages)

    for i, page in enumerate(pages):
        narration_text = page.text
        if i == total_pages - 1 and story.moral:
            moral_prefix = '。这个故事告诉我们：' if story.language == 'zh' else '. The moral of this story is: '
            narration_text += f"{moral_prefix}{story.moral}"
        if narration_text:
            audio_url, duration = service.generate_page_narration(
                story_id=story.id,
                page_number=page.page_number,
                narration_text=narration_text,
                voice=voice,
            )
            if audio_url:
                StoryAudio.objects.create(
                    page=page,
                    audio_type='narration',
                    voice_id=voice,
                    audio_url=audio_url,
                    duration_seconds=duration,
                )

        # Progress is managed by the parent pipeline (phase-completion
        # based) — don't write here, it used to race with other phases.

    logger.info(f"Audio generated: story={story.id}, voice={voice}")


def _generate_quiz(job, story):
    """Phase 4: Generate comprehension quiz with read-aloud audio."""

    from .services.quiz_generation import generate_quiz
    from .models import StoryQuiz

    questions = generate_quiz(story)
    if not questions:
        logger.warning(f"No quiz generated for story {story.id}")
        return

    # Generate read-aloud audio for each question
    _generate_quiz_audio(story, questions)

    StoryQuiz.objects.create(story=story, questions=questions)
    logger.info(f"Quiz generated: story={story.id}, {len(questions)} questions")


def _generate_quiz_audio(story, questions):
    """Generate TTS audio for each quiz question and upload to R2."""
    from .services.audio_generation import AudioGenerationService
    from .services.r2_storage import upload_to_r2

    service = AudioGenerationService()
    lang = story.language or 'en'

    # Pick voice based on story language
    voice_map = {
        'zh': 'zh_female_xiaoxue_uranus_bigtts',
        'en': 'en_female_dacey_uranus_bigtts',
        'bilingual': 'zh_female_xiaoxue_uranus_bigtts',
    }
    voice = voice_map.get(lang, 'en_female_dacey_uranus_bigtts')

    letters = ['A', 'B', 'C', 'D']

    for i, q in enumerate(questions):
        try:
            # Build read-aloud text: question + choices
            choices_text = '. '.join(
                f"{letters[j]}, {c}" for j, c in enumerate(q['choices'])
            )
            full_text = f"{q['question']}. {choices_text}"

            audio_bytes = service._call_tts(full_text, voice)
            if audio_bytes:
                r2_path = f"stories/{story.id}/quiz_q{i + 1}.mp3"
                audio_url = upload_to_r2(audio_bytes, r2_path)
                if audio_url:
                    q['audio_url'] = audio_url
                    logger.info(f"Quiz audio generated: story={story.id}, q{i + 1}")
        except Exception as e:
            logger.warning(f"Quiz audio failed for story {story.id} q{i + 1}: {e}")


def _generate_vocab_illustrations(job, story):
    """Phase 5: Generate cute illustrations for vocabulary flashcards."""

    from .services.image_generation import ImageGenerationService

    # Collect all unique vocabulary words across pages
    all_words = []
    seen = set()
    for page in story.pages.all():
        for v in (page.vocabulary or []):
            word = v.get('word', '')
            if word and word not in seen:
                seen.add(word)
                all_words.append(word)

    if not all_words:
        return

    service = ImageGenerationService()
    word_to_url = service.generate_vocab_illustrations(story.id, all_words)

    if not word_to_url:
        logger.warning(f"No vocab illustrations generated for story {story.id}")
        return

    # Update each page's vocabulary with image_url
    for page in story.pages.all():
        vocab = page.vocabulary or []
        updated = False
        for v in vocab:
            if v.get('word') in word_to_url:
                v['image_url'] = word_to_url[v['word']]
                updated = True
        if updated:
            page.vocabulary = vocab
            page.save(update_fields=['vocabulary'])

    logger.info(f"Vocab illustrations: story={story.id}, {len(word_to_url)}/{len(all_words)} words")
