import io
import re
import time
import base64
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
    "FRAMING: Show every character FULLY within the frame — include the entire head "
    "and body, never crop or cut off faces/heads/limbs. Keep a safe margin around "
    "the subjects so nothing touches the edges. Medium wide shot, characters "
    "centered in the composition. "
)

COLORING_PREFIX = (
    "Black and white coloring book page for children. "
    "STRICT RULES: ONLY black outlines on pure white background. "
    "NO colors, NO shading, NO grey, NO gradients, NO fill. "
    "Thick bold black line art, simple clean outlines, large empty areas to color in. "
    "Style: children's coloring book, cute cartoon, uncolored. "
    "Do NOT include any text, words, or letters. "
)

# Polling config for async APIs (APImart/seedance fallback)
POLL_INTERVAL = 3
MAX_POLL_ATTEMPTS = 60


class ImageGenerationService:
    """
    Image generation with Yunwu (gpt-image-1) as primary provider
    and APImart (seedance-4-5) as fallback.
    """

    MAX_RETRIES = 3
    RETRY_DELAY = 10
    IMAGE_RATIO = "16:9"

    # gpt-image-1 size mapping (ratio -> pixel dimensions)
    GPT_IMAGE_SIZES = {
        "16:9": "1536x1024",
        "1:1": "1024x1024",
        "9:16": "1024x1536",
    }

    def __init__(self):
        # Primary: Yunwu (with ordered key fallback chain)
        self.yunwu_api_keys = settings.YUNWU_API_KEYS or ([settings.YUNWU_API_KEY] if settings.YUNWU_API_KEY else [])
        self.yunwu_base_url = settings.YUNWU_BASE_URL
        self.yunwu_model = settings.YUNWU_IMAGE_MODEL

        # Fallback: APImart
        self.apimart_api_key = settings.APIMART_API_KEY
        self.apimart_base_url = settings.APIMART_BASE_URL
        self.apimart_model = settings.AI_IMAGE_MODEL

    # ── Public API ───────────────────────────────────────────────

    def generate_page_image(self, story_id, page_number, image_prompt):
        """Generate a single 16:9 image for a story page."""
        enhanced_prompt = STYLE_PREFIX + image_prompt

        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                # Try Yunwu first
                image_data = self._yunwu_generate(enhanced_prompt, size=self.IMAGE_RATIO)
                if image_data:
                    r2_url = self._save_image_data(image_data, story_id, page_number)
                    if r2_url:
                        logger.info(f"[yunwu] Image generated for story {story_id}, page {page_number}")
                        return r2_url

                # Fallback to APImart
                logger.info(f"[yunwu] Failed, falling back to APImart for story {story_id}, page {page_number}")
                url = self._apimart_generate(enhanced_prompt, size=self.IMAGE_RATIO)
                if url:
                    r2_url = self._upload_to_r2(url, story_id, page_number)
                    final_url = r2_url or url
                    logger.info(f"[apimart] Image generated for story {story_id}, page {page_number}")
                    return final_url

            except Exception as e:
                logger.error(f"Image generation error for story {story_id}, page {page_number}: {e}")

            if attempt < self.MAX_RETRIES:
                logger.warning(f"Image failed for story {story_id} page {page_number}, retry {attempt}/{self.MAX_RETRIES}")
                time.sleep(self.RETRY_DELAY)

        return ''

    def generate_quad_panel(self, story_id, pages):
        """Generate 4 scenes in a 2x2 grid, split into separate images."""
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
                # Try Yunwu first
                image_data = self._yunwu_generate(combined_prompt, size=self.IMAGE_RATIO)
                if image_data:
                    results = self._split_grid_from_data(image_data, story_id, pages)
                    if results:
                        logger.info(f"[yunwu] Quad panel generated for story {story_id}")
                        return results

                # Fallback to APImart
                logger.info(f"[yunwu] Quad panel failed, falling back to APImart for story {story_id}")
                image_url = self._apimart_generate(combined_prompt, size=self.IMAGE_RATIO)
                if image_url:
                    results = self._split_grid_and_upload(image_url, story_id, pages)
                    if results:
                        logger.info(f"[apimart] Quad panel generated for story {story_id}")
                        return results

            except Exception as e:
                logger.error(f"Quad panel error for story {story_id}: {e}")

            if attempt < self.MAX_RETRIES:
                time.sleep(self.RETRY_DELAY)

        return []

    def generate_coloring_pages(self, story_id, pages):
        """Generate coloring book line art versions for story pages."""
        results = []
        i = 0
        while i < len(pages):
            if i > 0:
                time.sleep(3)

            batch = pages[i:i + 4]
            batch_size = len(batch)

            if batch_size >= 2:
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
                batch_results = self._generate_and_split_coloring(combined_prompt, story_id, batch)
                if batch_results:
                    results.extend(batch_results)
                else:
                    for page_num, prompt in batch:
                        time.sleep(3)
                        url = self._generate_single_coloring(story_id, page_num, prompt)
                        if url:
                            results.append((page_num, url))
            else:
                page_num, prompt = batch[0]
                url = self._generate_single_coloring(story_id, page_num, prompt)
                if url:
                    results.append((page_num, url))

            i += batch_size

        logger.info(f"Coloring pages generated: story={story_id}, {len(results)}/{len(pages)} pages")
        return results

    # ── Yunwu (primary) ──────────────────────────────────────────

    def _yunwu_generate(self, prompt, size=None):
        """
        Generate image via Yunwu API using Gemini image model through chat/completions.
        Tries each key in yunwu_api_keys in order; returns bytes on first success.
        """
        if not self.yunwu_api_keys:
            return None

        url = f"{self.yunwu_base_url}/chat/completions"
        payload = {
            "model": self.yunwu_model,
            "messages": [
                {
                    "role": "user",
                    "content": f"Generate a high-resolution 4K image: {prompt}"
                }
            ],
        }

        for idx, key in enumerate(self.yunwu_api_keys, start=1):
            headers = {
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            }
            label = f"key#{idx}({key[:12]}...)"
            try:
                resp = requests.post(url, json=payload, headers=headers, timeout=120)
                resp.raise_for_status()
                data = resp.json()

                if "choices" not in data or not data["choices"]:
                    logger.warning(f"[yunwu] {label} no choices in response, trying next key")
                    continue

                content = data["choices"][0].get("message", {}).get("content", "")

                match = re.search(r'data:image/[a-z]+;base64,([A-Za-z0-9+/=\s]+)', content)
                if match:
                    b64_data = match.group(1).replace('\n', '').replace(' ', '')
                    image_bytes = base64.b64decode(b64_data)
                    logger.info(f"[yunwu] {label} generated {len(image_bytes)} bytes")
                    return image_bytes

                logger.warning(f"[yunwu] {label} no base64 in response (content len: {len(content)}), trying next key")
            except Exception as e:
                logger.warning(f"[yunwu] {label} failed: {e}, trying next key")

        logger.error(f"[yunwu] all {len(self.yunwu_api_keys)} keys exhausted")
        return None

    def _save_image_data(self, image_bytes, story_id, page_number):
        """Upload raw image bytes to R2."""
        try:
            r2_path = f"stories/{story_id}/page_{page_number}.jpg"
            # Convert to JPEG if needed
            img = Image.open(io.BytesIO(image_bytes))
            buf = io.BytesIO()
            img.convert('RGB').save(buf, format='JPEG', quality=90)
            return upload_to_r2(buf.getvalue(), r2_path)
        except Exception as e:
            logger.warning(f"R2 upload failed for story {story_id} page {page_number}: {e}")
            return None

    def _split_grid_from_data(self, image_bytes, story_id, pages):
        """Split image bytes into 2x2 grid panels and upload each."""
        try:
            img = Image.open(io.BytesIO(image_bytes))
            w, h = img.size
            mw, mh = w // 2, h // 2

            crops = [
                (0, 0, mw, mh),
                (mw, 0, w, mh),
                (0, mh, mw, h),
                (mw, mh, w, h),
            ]

            results = []
            for i, (page_num, _) in enumerate(pages):
                if i >= 4:
                    break
                panel = img.crop(crops[i]).convert('RGB')
                buf = io.BytesIO()
                panel.save(buf, format='JPEG', quality=90)
                r2_url = upload_to_r2(buf.getvalue(), f"stories/{story_id}/page_{page_num}.jpg")
                if r2_url:
                    results.append((page_num, r2_url))

            return results
        except Exception as e:
            logger.error(f"Grid split failed for story {story_id}: {e}")
            return []

    # ── APImart (fallback) ───────────────────────────────────────

    def _apimart_generate(self, prompt, size=None):
        """
        Generate image via APImart (async task-based).
        Returns image URL on success, None on failure.
        """
        if not self.apimart_api_key:
            return None

        if size is None:
            size = self.IMAGE_RATIO

        try:
            task_id = self._submit_task(prompt, size=size)
            if not task_id:
                return None
            return self._poll_task(task_id)
        except Exception as e:
            logger.error(f"[apimart] Image generation failed: {e}")
            return None

    def _submit_task(self, prompt, size=None):
        """Submit image generation request to APImart, returns task_id."""
        if size is None:
            size = self.IMAGE_RATIO
        url = f"{self.apimart_base_url}/images/generations"
        headers = {
            "Authorization": f"Bearer {self.apimart_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.apimart_model,
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
                logger.info(f"[apimart] Image task submitted: {task_id}")
                return task_id

        logger.error(f"[apimart] No task_id in response: {data}")
        return None

    def _poll_task(self, task_id):
        """Poll APImart task status until completed, returns image URL."""
        url = f"{self.apimart_base_url}/tasks/{task_id}"
        headers = {"Authorization": f"Bearer {self.apimart_api_key}"}

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
                logger.error(f"[apimart] Task completed but no image URL: {data}")
                return None

            elif status in ("failed", "cancelled"):
                logger.error(f"[apimart] Image task {task_id} {status}: {data}")
                return None

        logger.error(f"[apimart] Image task {task_id} timed out after {MAX_POLL_ATTEMPTS * POLL_INTERVAL}s")
        return None

    # ── Shared utilities ─────────────────────────────────────────

    def _split_grid_and_upload(self, image_url, story_id, pages):
        """Download image URL, split into 2x2 grid, upload each quadrant to R2."""
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
        """Download image from URL and upload to R2."""
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

    def _generate_single_coloring(self, story_id, page_number, image_prompt):
        """Generate a single coloring page line art."""
        enhanced_prompt = COLORING_PREFIX + image_prompt

        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                # Try Yunwu first
                image_data = self._yunwu_generate(enhanced_prompt, size=self.IMAGE_RATIO)
                if image_data:
                    img = Image.open(io.BytesIO(image_data))
                    bw = self._to_pure_lineart(img)
                    buf = io.BytesIO()
                    bw.save(buf, format='JPEG', quality=90)
                    r2_path = f"stories/{story_id}/coloring_page_{page_number}.jpg"
                    r2_url = upload_to_r2(buf.getvalue(), r2_path)
                    if r2_url:
                        logger.info(f"[yunwu] Coloring page generated for story {story_id}, page {page_number}")
                        return r2_url

                # Fallback to APImart
                image_url = self._apimart_generate(enhanced_prompt, size=self.IMAGE_RATIO)
                if image_url:
                    r2_path = f"stories/{story_id}/coloring_page_{page_number}.jpg"
                    r2_url = self._download_convert_upload(image_url, r2_path)
                    if r2_url:
                        return r2_url
                    return image_url

            except Exception as e:
                logger.error(f"Coloring generation error for story {story_id}, page {page_number}: {e}")

            if attempt < self.MAX_RETRIES:
                time.sleep(self.RETRY_DELAY)

        return ''

    def _generate_and_split_coloring(self, prompt, story_id, pages):
        """Generate a quad-panel coloring image, split and upload each panel."""
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                # Try Yunwu first
                image_data = self._yunwu_generate(prompt, size=self.IMAGE_RATIO)
                if image_data:
                    results = self._split_coloring_from_data(image_data, story_id, pages)
                    if results:
                        return results

                # Fallback to APImart
                image_url = self._apimart_generate(prompt, size=self.IMAGE_RATIO)
                if image_url:
                    return self._split_coloring_grid_and_upload(image_url, story_id, pages)

            except Exception as e:
                logger.error(f"Coloring quad panel error for story {story_id}: {e}")

            if attempt < self.MAX_RETRIES:
                time.sleep(self.RETRY_DELAY)

        return []

    def _split_coloring_from_data(self, image_bytes, story_id, pages):
        """Split coloring image bytes into panels, convert to B&W, upload."""
        try:
            img = Image.open(io.BytesIO(image_bytes))
            w, h = img.size
            mw, mh = w // 2, h // 2

            crops = [
                (0, 0, mw, mh),
                (mw, 0, w, mh),
                (0, mh, mw, h),
                (mw, mh, w, h),
            ]

            results = []
            for i, (page_num, _) in enumerate(pages):
                if i >= 4:
                    break
                panel = self._to_pure_lineart(img.crop(crops[i]))
                buf = io.BytesIO()
                panel.save(buf, format='JPEG', quality=90)
                r2_url = upload_to_r2(buf.getvalue(), f"stories/{story_id}/coloring_page_{page_num}.jpg")
                if r2_url:
                    results.append((page_num, r2_url))

            return results
        except Exception as e:
            logger.error(f"Coloring grid split failed for story {story_id}: {e}")
            return []

    def _split_coloring_grid_and_upload(self, image_url, story_id, pages):
        """Download coloring grid image URL, split into panels, force B&W, upload."""
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

        def adjust(x):
            if x < 80:
                return int(x * 0.6)
            elif x < 180:
                return int(180 + (x - 80) * 0.75)
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

    # ── Vocabulary illustrations ─────────────────────────────────

    VOCAB_ILLUSTRATION_PREFIX = (
        "Grid of cute cartoon illustrations for children's vocabulary flashcards, "
        "bright cheerful colors, simple clean style, white background between panels, "
        "each panel shows ONE object/concept clearly as a simple cartoon drawing. "
        "Child-safe, friendly, NO violence, NO scary elements. "
        "ABSOLUTELY CRITICAL RULE: The image must contain ZERO text. "
        "No letters, no words, no numbers, no labels, no captions, no speech bubbles, "
        "no signs, no banners, no writing of ANY kind in ANY language. "
        "Each panel must be a PURE illustration with no text whatsoever. "
    )

    def generate_vocab_illustrations(self, story_id, words):
        """Generate grid illustrations for vocabulary words.

        Cap each batch at 4 words (2x2 grid). Larger grids (3x3 / 4x4)
        are unreliable: the upstream model often paints fewer panels than
        requested, so a request for 8 words ends up with two of them
        painted side-by-side inside what we treat as a single cell —
        producing the cropped/duplicated flashcards users have reported.
        """
        if not words:
            return {}

        BATCH_SIZE = 4
        result = {}
        for batch_start in range(0, len(words), BATCH_SIZE):
            batch = words[batch_start:batch_start + BATCH_SIZE]
            batch_result = self._generate_vocab_batch(story_id, batch)
            result.update(batch_result)
            if batch_start + BATCH_SIZE < len(words):
                time.sleep(2)

        return result

    def _generate_vocab_batch(self, story_id, words):
        """Generate one grid of vocab illustrations for up to 16 words."""
        n = len(words)
        if n == 0:
            return {}

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

        labels = [f"a cute cartoon illustration of '{word}'" for word in words]
        grid_desc = ', '.join(labels)
        prompt = (
            f"{self.VOCAB_ILLUSTRATION_PREFIX}"
            f"{cols}x{rows} grid layout with clear white borders between panels. "
            f"{grid_desc}"
        )

        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                # Try Yunwu first
                image_data = self._yunwu_generate(prompt, size=self.IMAGE_RATIO)
                if image_data:
                    result = self._split_vocab_from_data(image_data, story_id, words, cols, rows)
                    if result:
                        return result

                # Fallback to APImart
                image_url = self._apimart_generate(prompt, size=self.IMAGE_RATIO)
                if image_url:
                    return self._split_vocab_grid(image_url, story_id, words, cols, rows)

            except Exception as e:
                logger.error(f"Vocab illustration error for story {story_id}: {e}")

            if attempt < self.MAX_RETRIES:
                time.sleep(self.RETRY_DELAY)

        return {}

    @staticmethod
    def _trim_cell(cell, margin_pct=0.06):
        """Trim a percentage from each edge to remove grid borders."""
        w, h = cell.size
        mx = int(w * margin_pct)
        my = int(h * margin_pct)
        return cell.crop((mx, my, w - mx, h - my))

    def _split_vocab_from_data(self, image_bytes, story_id, words, cols, rows):
        """Split vocab grid image bytes into individual cells and upload."""
        try:
            img = Image.open(io.BytesIO(image_bytes))
            w, h = img.size
            cell_w = w // cols
            cell_h = h // rows

            result = {}
            for i, word in enumerate(words):
                row = i // cols
                col = i % cols
                box = (col * cell_w, row * cell_h, (col + 1) * cell_w, (row + 1) * cell_h)
                cell = self._trim_cell(img.crop(box)).convert('RGB')

                buf = io.BytesIO()
                cell.save(buf, format='JPEG', quality=85)
                safe_word = word.replace(' ', '_').replace('/', '_')[:20]
                r2_path = f"stories/{story_id}/vocab_{i}_{safe_word}.jpg"
                url = upload_to_r2(buf.getvalue(), r2_path)
                if url:
                    result[word] = url

            return result
        except Exception as e:
            logger.error(f"Vocab grid split failed for story {story_id}: {e}")
            return {}

    def _split_vocab_grid(self, image_url, story_id, words, cols, rows):
        """Download grid image URL, split into individual cells, upload each."""
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
                cell = self._trim_cell(img.crop(box))

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
