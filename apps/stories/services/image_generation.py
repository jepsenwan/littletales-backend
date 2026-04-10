import io
import time
import logging
import requests
from PIL import Image
from django.conf import settings
from .r2_storage import upload_to_r2

logger = logging.getLogger(__name__)

STYLE_PREFIX = (
    "Children's picture book illustration, watercolor style, "
    "soft warm colors, cute and friendly characters, "
    "gentle lighting, storybook aesthetic. "
    "IMPORTANT: Do NOT include any text, words, letters, or writing in the image. "
    "No speech bubbles, no captions, no signs with text. Pure illustration only. "
)

COLORING_PREFIX = (
    "Black and white coloring book page for children. "
    "STRICT RULES: ONLY black outlines on pure white background. "
    "NO colors, NO shading, NO grey, NO gradients, NO fill. "
    "Thick bold black line art, simple clean outlines, large empty areas to color in. "
    "Style: children's coloring book, cute cartoon, uncolored. "
    "Do NOT include any text, words, or letters. "
)

POLL_INTERVAL = 3  # seconds
MAX_POLL_ATTEMPTS = 60  # max ~3 minutes per image


class ImageGenerationService:
    def __init__(self):
        self.api_key = settings.APIMART_API_KEY
        self.base_url = settings.APIMART_BASE_URL
        self.model = settings.AI_IMAGE_MODEL

    MAX_RETRIES = 3
    RETRY_DELAY = 10  # seconds between retries

    IMAGE_RATIO = "16:9"

    def generate_page_image(self, story_id, page_number, image_prompt):
        """
        Generate a single 16:9 image for a story page.
        Retries up to MAX_RETRIES times on failure.
        Returns the public URL of the uploaded image.
        """
        enhanced_prompt = STYLE_PREFIX + image_prompt

        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                task_id = self._submit_task(enhanced_prompt, size=self.IMAGE_RATIO)
                if not task_id:
                    if attempt < self.MAX_RETRIES:
                        logger.warning(f"Image submit failed for story {story_id} page {page_number}, retry {attempt}/{self.MAX_RETRIES}")
                        time.sleep(self.RETRY_DELAY)
                        continue
                    return ''

                image_url = self._poll_task(task_id)
                if image_url:
                    r2_url = self._upload_to_r2(image_url, story_id, page_number)
                    final_url = r2_url or image_url
                    logger.info(f"Image generated for story {story_id}, page {page_number}, r2={'yes' if r2_url else 'no'}")
                    return final_url

                if attempt < self.MAX_RETRIES:
                    logger.warning(f"Image task failed for story {story_id} page {page_number}, retry {attempt}/{self.MAX_RETRIES}")
                    time.sleep(self.RETRY_DELAY)
                    continue
                return ''

            except Exception as e:
                logger.error(f"Image generation error for story {story_id}, page {page_number}: {e}")
                if attempt < self.MAX_RETRIES:
                    time.sleep(self.RETRY_DELAY)
                    continue
                return ''

        return ''

    def generate_quad_panel(self, story_id, pages):
        """
        Generate a single 1:1 image containing 4 scenes in a 2x2 grid,
        then split into 4 separate images and upload each to R2.
        pages: list of (page_number, image_prompt) tuples, length 2-4.
        Returns list of (page_number, url) tuples.
        """
        labels = ['TOP-LEFT', 'TOP-RIGHT', 'BOTTOM-LEFT', 'BOTTOM-RIGHT']
        panel_descs = ' '.join(
            f"{labels[i]}: {prompt}" for i, (_, prompt) in enumerate(pages)
        )
        n = len(pages)
        grid_desc = "Four-panel grid illustration, 2x2 layout" if n == 4 else f"{n}-panel grid illustration"

        combined_prompt = (
            f"{STYLE_PREFIX}"
            f"{grid_desc}, each panel is a separate scene with clear borders between panels. "
            f"{panel_descs}"
        )

        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                task_id = self._submit_task(combined_prompt, size=self.IMAGE_RATIO)
                if not task_id:
                    if attempt < self.MAX_RETRIES:
                        time.sleep(self.RETRY_DELAY)
                        continue
                    return []

                image_url = self._poll_task(task_id)
                if image_url:
                    results = self._split_grid_and_upload(image_url, story_id, pages)
                    if results:
                        page_nums = [p[0] for p in pages]
                        logger.info(f"Quad panel generated for story {story_id}, pages {page_nums}")
                        return results

                if attempt < self.MAX_RETRIES:
                    logger.warning(f"Quad panel failed for story {story_id}, retry {attempt}/{self.MAX_RETRIES}")
                    time.sleep(self.RETRY_DELAY)
                    continue
                return []

            except Exception as e:
                logger.error(f"Quad panel error for story {story_id}: {e}")
                if attempt < self.MAX_RETRIES:
                    time.sleep(self.RETRY_DELAY)
                    continue
                return []

        return []

    def _split_grid_and_upload(self, image_url, story_id, pages):
        """Download a 1:1 image, split into 2x2 grid, upload each quadrant to R2."""
        try:
            resp = requests.get(image_url, timeout=30)
            resp.raise_for_status()

            img = Image.open(io.BytesIO(resp.content))
            w, h = img.size
            mw, mh = w // 2, h // 2

            # 2x2 grid positions: top-left, top-right, bottom-left, bottom-right
            crops = [
                (0, 0, mw, mh),
                (mw, 0, w, mh),
                (0, mh, mw, h),
                (mw, mh, w, h),
            ]

            def to_bytes(im):
                buf = io.BytesIO()
                im.save(buf, format='JPEG', quality=90)
                return buf.getvalue()

            results = []
            for i, (page_num, _) in enumerate(pages):
                if i >= 4:
                    break
                panel = img.crop(crops[i])
                panel_bytes = to_bytes(panel)
                r2_url = upload_to_r2(panel_bytes, f"stories/{story_id}/page_{page_num}.jpg")
                if r2_url:
                    results.append((page_num, r2_url))

            logger.info(f"Grid split & uploaded: story {story_id}, {len(results)} panels")
            return results

        except Exception as e:
            logger.error(f"Grid split/upload failed for story {story_id}: {e}")
            return []

    def _upload_to_r2(self, image_url, story_id, page_number):
        """Download image from apimart and upload to R2 for permanent storage."""
        try:
            resp = requests.get(image_url, timeout=30)
            resp.raise_for_status()
            r2_path = f"stories/{story_id}/page_{page_number}.jpg"
            r2_url = upload_to_r2(resp.content, r2_path)
            logger.info(f"Image uploaded to R2: {r2_path}")
            return r2_url
        except Exception as e:
            logger.warning(f"R2 upload failed for story {story_id} page {page_number}: {e}")
            return None

    def _submit_task(self, prompt, size=None):
        """Submit image generation request, returns task_id."""
        if size is None:
            size = self.IMAGE_RATIO
        url = f"{self.base_url}/images/generations"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "prompt": prompt,
            "n": 1,
            "size": size,
        }

        resp = requests.post(url, json=payload, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        if "data" in data and len(data["data"]) > 0:
            task_id = data["data"][0].get("task_id")
            if task_id:
                logger.info(f"Image task submitted: {task_id}")
                return task_id

        logger.error(f"No task_id in response: {data}")
        return None

    def generate_coloring_pages(self, story_id, pages):
        """
        Generate coloring book line art versions for story pages.
        Uses quad-panel mode (4 pages per API call) for efficiency.
        pages: list of (page_number, image_prompt) tuples.
        Returns list of (page_number, url) tuples.
        """
        results = []

        # Process in batches of 4
        i = 0
        while i < len(pages):
            if i > 0:
                time.sleep(3)

            batch = pages[i:i + 4]
            batch_size = len(batch)

            if batch_size >= 2:
                # Quad-panel coloring generation
                labels = ['TOP-LEFT', 'TOP-RIGHT', 'BOTTOM-LEFT', 'BOTTOM-RIGHT']
                panel_descs = ' '.join(
                    f"{labels[j]}: {prompt}" for j, (_, prompt) in enumerate(batch)
                )
                grid_desc = "Four-panel grid" if batch_size == 4 else f"{batch_size}-panel grid"

                combined_prompt = (
                    f"{COLORING_PREFIX}"
                    f"{grid_desc}, each panel is a separate scene with clear borders between panels. "
                    f"{panel_descs}"
                )

                batch_results = self._generate_and_split_coloring(
                    combined_prompt, story_id, batch
                )
                if batch_results:
                    results.extend(batch_results)
                else:
                    # Fallback: generate individually
                    for page_num, prompt in batch:
                        time.sleep(3)
                        url = self._generate_single_coloring(story_id, page_num, prompt)
                        if url:
                            results.append((page_num, url))
            else:
                # Single page
                page_num, prompt = batch[0]
                url = self._generate_single_coloring(story_id, page_num, prompt)
                if url:
                    results.append((page_num, url))

            i += batch_size

        logger.info(f"Coloring pages generated: story={story_id}, {len(results)}/{len(pages)} pages")
        return results

    def _generate_single_coloring(self, story_id, page_number, image_prompt):
        """Generate a single coloring page line art."""
        enhanced_prompt = COLORING_PREFIX + image_prompt

        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                task_id = self._submit_task(enhanced_prompt, size=self.IMAGE_RATIO)
                if not task_id:
                    if attempt < self.MAX_RETRIES:
                        time.sleep(self.RETRY_DELAY)
                        continue
                    return ''

                image_url = self._poll_task(task_id)
                if image_url:
                    r2_path = f"stories/{story_id}/coloring_page_{page_number}.jpg"
                    r2_url = self._download_convert_upload(image_url, r2_path)
                    return r2_url or image_url

                if attempt < self.MAX_RETRIES:
                    time.sleep(self.RETRY_DELAY)
                    continue
                return ''

            except Exception as e:
                logger.error(f"Coloring generation error for story {story_id}, page {page_number}: {e}")
                if attempt < self.MAX_RETRIES:
                    time.sleep(self.RETRY_DELAY)
                    continue
                return ''

        return ''

    def _generate_and_split_coloring(self, prompt, story_id, pages):
        """Generate a quad-panel coloring image, split and upload each panel."""
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                task_id = self._submit_task(prompt, size=self.IMAGE_RATIO)
                if not task_id:
                    if attempt < self.MAX_RETRIES:
                        time.sleep(self.RETRY_DELAY)
                        continue
                    return []

                image_url = self._poll_task(task_id)
                if image_url:
                    return self._split_coloring_grid_and_upload(image_url, story_id, pages)

                if attempt < self.MAX_RETRIES:
                    time.sleep(self.RETRY_DELAY)
                    continue
                return []

            except Exception as e:
                logger.error(f"Coloring quad panel error for story {story_id}: {e}")
                if attempt < self.MAX_RETRIES:
                    time.sleep(self.RETRY_DELAY)
                    continue
                return []

        return []

    def _split_coloring_grid_and_upload(self, image_url, story_id, pages):
        """Download coloring grid image, split into panels, force B&W, upload each to R2."""
        try:
            resp = requests.get(image_url, timeout=30)
            resp.raise_for_status()

            img = Image.open(io.BytesIO(resp.content))
            w, h = img.size
            mw, mh = w // 2, h // 2

            crops = [
                (0, 0, mw, mh),
                (mw, 0, w, mh),
                (0, mh, mw, h),
                (mw, mh, w, h),
            ]

            def to_bytes(im):
                buf = io.BytesIO()
                im.save(buf, format='JPEG', quality=90)
                return buf.getvalue()

            results = []
            for i, (page_num, _) in enumerate(pages):
                if i >= 4:
                    break
                panel = self._to_pure_lineart(img.crop(crops[i]))
                panel_bytes = to_bytes(panel)
                r2_url = upload_to_r2(panel_bytes, f"stories/{story_id}/coloring_page_{page_num}.jpg")
                if r2_url:
                    results.append((page_num, r2_url))

            logger.info(f"Coloring grid split & uploaded: story {story_id}, {len(results)} panels")
            return results

        except Exception as e:
            logger.error(f"Coloring grid split/upload failed for story {story_id}: {e}")
            return []

    @staticmethod
    def _to_pure_lineart(img):
        """Lighten image to clean line art: reduce dark fills, keep outlines."""
        gray = img.convert('L')
        # Gentle approach: boost brightness to wash out gray fills
        # Only keep the strongest lines (< 80 stays dark, 80-180 fades, >180 white)
        def adjust(x):
            if x < 80:
                return int(x * 0.6)  # darken actual lines slightly
            elif x < 180:
                return int(180 + (x - 80) * 0.75)  # push mid-grays toward white
            else:
                return 255
        cleaned = gray.point(adjust)
        return cleaned.convert('RGB')

    def _download_convert_upload(self, image_url, r2_path):
        """Download image, convert to pure B&W line art, upload to R2."""
        try:
            resp = requests.get(image_url, timeout=30)
            resp.raise_for_status()
            img = Image.open(io.BytesIO(resp.content))
            bw = self._to_pure_lineart(img)
            buf = io.BytesIO()
            bw.save(buf, format='JPEG', quality=90)
            return upload_to_r2(buf.getvalue(), r2_path)
        except Exception as e:
            logger.warning(f"Coloring convert/upload failed for {r2_path}: {e}")
            return None

    def _download_and_upload(self, image_url, r2_path):
        """Download image and upload to R2."""
        try:
            resp = requests.get(image_url, timeout=30)
            resp.raise_for_status()
            return upload_to_r2(resp.content, r2_path)
        except Exception as e:
            logger.warning(f"R2 upload failed for {r2_path}: {e}")
            return None

    VOCAB_ILLUSTRATION_PREFIX = (
        "Grid of cute cartoon illustrations for children's vocabulary flashcards, "
        "bright cheerful colors, simple clean style, white background between panels, "
        "each panel shows ONE object/concept clearly. "
        "Child-safe, friendly, NO violence, NO scary elements. "
        "CRITICAL: absolutely NO text, NO letters, NO numbers, NO labels, NO words, NO captions anywhere in the image. Pure illustrations only. "
    )

    def generate_vocab_illustrations(self, story_id, words):
        """
        Generate grid illustrations for vocabulary words and split into individual images.
        Batches in groups of up to 16 (4x4 grid). Multiple API calls for >16 words.
        Returns dict: {word: image_url}
        """
        if not words:
            return {}

        result = {}
        # Process in batches of 16
        for batch_start in range(0, len(words), 16):
            batch = words[batch_start:batch_start + 16]
            batch_result = self._generate_vocab_batch(story_id, batch)
            result.update(batch_result)
            if batch_start + 16 < len(words):
                time.sleep(3)

        return result

    def _generate_vocab_batch(self, story_id, words):
        """Generate one grid of vocab illustrations for up to 16 words."""
        n = len(words)
        if n == 0:
            return {}

        # Determine grid layout
        if n <= 4:
            cols, rows = 2, 2
        elif n <= 6:
            cols, rows = 3, 2
        elif n <= 9:
            cols, rows = 3, 3
        elif n <= 12:
            cols, rows = 4, 3
        else:
            cols, rows = 4, 4
            words = words[:16]
            n = len(words)

        # Build prompt: each cell describes one word (avoid numbers to prevent AI drawing them)
        labels = []
        for i, word in enumerate(words):
            labels.append(f"a cute cartoon illustration of '{word}'")

        grid_desc = ', '.join(labels)
        prompt = (
            f"{self.VOCAB_ILLUSTRATION_PREFIX}"
            f"{cols}x{rows} grid layout with clear white borders between panels. "
            f"{grid_desc}"
        )

        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                task_id = self._submit_task(prompt, size=self.IMAGE_RATIO)
                if not task_id:
                    if attempt < self.MAX_RETRIES:
                        time.sleep(self.RETRY_DELAY)
                        continue
                    return {}

                image_url = self._poll_task(task_id)
                if image_url:
                    return self._split_vocab_grid(image_url, story_id, words, cols, rows)

                if attempt < self.MAX_RETRIES:
                    time.sleep(self.RETRY_DELAY)
                    continue
                return {}

            except Exception as e:
                logger.error(f"Vocab illustration error for story {story_id}: {e}")
                if attempt < self.MAX_RETRIES:
                    time.sleep(self.RETRY_DELAY)
                    continue
                return {}

        return {}

    def _split_vocab_grid(self, image_url, story_id, words, cols, rows):
        """Download grid image, split into individual cells, upload each."""
        try:
            resp = requests.get(image_url, timeout=30)
            resp.raise_for_status()

            img = Image.open(io.BytesIO(resp.content))
            w, h = img.size
            cell_w = w // cols
            cell_h = h // rows

            result = {}
            for i, word in enumerate(words):
                row = i // cols
                col = i % cols
                box = (col * cell_w, row * cell_h, (col + 1) * cell_w, (row + 1) * cell_h)
                cell = img.crop(box)

                buf = io.BytesIO()
                cell.save(buf, format='JPEG', quality=85)
                safe_word = word.replace(' ', '_').replace('/', '_')[:20]
                r2_path = f"stories/{story_id}/vocab_{i}_{safe_word}.jpg"
                url = upload_to_r2(buf.getvalue(), r2_path)
                if url:
                    result[word] = url

            logger.info(f"Vocab illustrations generated: story={story_id}, {len(result)}/{len(words)} words")
            return result

        except Exception as e:
            logger.error(f"Vocab grid split failed for story {story_id}: {e}")
            return {}

    def _poll_task(self, task_id):
        """Poll task status until completed, returns image URL."""
        url = f"{self.base_url}/tasks/{task_id}"
        headers = {"Authorization": f"Bearer {self.api_key}"}

        for attempt in range(MAX_POLL_ATTEMPTS):
            time.sleep(POLL_INTERVAL)

            resp = requests.get(url, headers=headers, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            task_data = data.get("data", {})
            status = task_data.get("status", "")

            if status == "completed":
                result = task_data.get("result", {})
                images = result.get("images", [])
                if images:
                    urls = images[0].get("url", [])
                    if urls:
                        return urls[0] if isinstance(urls, list) else urls
                logger.error(f"Task completed but no image URL: {data}")
                return None

            elif status in ("failed", "cancelled"):
                logger.error(f"Image task {task_id} {status}: {data}")
                return None

        logger.error(f"Image task {task_id} timed out after {MAX_POLL_ATTEMPTS * POLL_INTERVAL}s")
        return None
