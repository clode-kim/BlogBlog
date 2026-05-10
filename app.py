import os
import json
import re
import io
import hmac
import hashlib
import time
import requests
from urllib.parse import urlencode
from xml.etree import ElementTree as ET
from flask import Flask, request, jsonify, render_template
from google import genai
from google.genai import types
from PIL import Image
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 80 * 1024 * 1024  # 80MB


def get_client():
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise ValueError("GEMINI_API_KEY가 설정되지 않았습니다. .env 파일을 확인해주세요.")
    return genai.Client(api_key=api_key)


def clean_html(html_text):
    # 블록 태그를 줄바꿈으로 변환 (문단 구조 보존)
    text = re.sub(r'<br\s*/?>', '\n', html_text, flags=re.IGNORECASE)
    text = re.sub(r'</?p[^>]*>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</?div[^>]*>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', '', text)
    for old, new in [('&nbsp;', ' '), ('&amp;', '&'), ('&lt;', '<'),
                     ('&gt;', '>'), ('&quot;', '"'), ('&#39;', "'")]:
        text = text.replace(old, new)
    # 줄 내 연속 공백 정리, 3줄 이상 빈줄은 2줄로
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def fetch_naver_blog_posts(blog_id, count=10):
    """Returns (posts, error_message)."""
    try:
        rss_url = f"https://rss.blog.naver.com/{blog_id}.xml"
        headers = {
            'User-Agent': (
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )
        }
        response = requests.get(rss_url, headers=headers, timeout=12)

        if response.status_code == 404:
            return [], f"블로그 ID '{blog_id}'를 찾을 수 없습니다."

        response.raise_for_status()

        try:
            root = ET.fromstring(response.content)
        except ET.ParseError:
            content = re.sub(r'<\?xml[^>]+\?>', '', response.text)
            root = ET.fromstring(content.encode('utf-8'))

        channel = root.find('channel')
        if channel is None:
            return [], "RSS 피드 형식이 올바르지 않습니다."

        posts = []
        for item in channel.findall('item')[:count]:
            title = item.findtext('title', '').strip()
            description = item.findtext('description', '')
            description = re.sub(r'<!\[CDATA\[|\]\]>', '', description)
            clean_content = clean_html(description)
            if title or clean_content:
                posts.append({'title': title, 'content': clean_content[:1500]})

        if not posts:
            return [], "블로그 글을 찾을 수 없습니다. RSS가 비공개 설정인지 확인해주세요."

        return posts, None

    except requests.Timeout:
        return [], "블로그 RSS 요청 시간이 초과됐습니다."
    except requests.RequestException as e:
        return [], f"블로그 RSS 요청 실패: {str(e)}"
    except Exception as e:
        return [], f"블로그 글 가져오기 실패: {str(e)}"


def search_coupang_products(keyword, limit=2):
    """쿠팡 파트너스 API로 상품 검색. Returns list of product dicts."""
    from urllib.parse import quote as urlquote
    access_key = os.environ.get("COUPANG_ACCESS_KEY", "")
    secret_key = os.environ.get("COUPANG_SECRET_KEY", "")
    if not access_key or not secret_key:
        return []

    try:
        method = "GET"
        path = "/v2/providers/affiliate_open_api/apis/openapi/v1/products/search"

        # 쿼리스트링을 URL과 서명에 동일하게 사용 (URL인코딩 적용)
        qs = f"keyword={urlquote(keyword, safe='')}&limit={limit}&subId="

        datetime_str = time.strftime('%y%m%d%H%M%S', time.gmtime())
        message = f"{datetime_str}{method}{path}{qs}"

        signature = hmac.new(
            secret_key.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()

        headers = {
            "Authorization": (
                f"CEA algorithm=HmacSHA256, access-key={access_key}, "
                f"signed-date={datetime_str}, signature={signature}"
            ),
            "Content-Type": "application/json;charset=UTF-8",
        }

        url = f"https://api-gateway.coupang.com{path}?{qs}"
        resp = requests.get(url, headers=headers, timeout=8)
        data = resp.json()

        products = []
        for item in (data.get("data", {}).get("productData") or [])[:limit]:
            name = item.get("productName", "")
            price = item.get("productPrice", 0)
            link = item.get("productUrl", "")
            img = item.get("productImage", "")
            if name and link:
                products.append({
                    "name": name[:40],
                    "price": f"{int(price):,}원" if price else "",
                    "url": link,
                    "image": img,
                })
        return products

    except Exception as e:
        app.logger.warning(f"Coupang API error for '{keyword}': {e}")
        return []


def pil_to_part(pil_img, original_mime=None):
    """PIL Image를 Gemini API Part로 변환."""
    fmt = pil_img.format or 'JPEG'
    mime_map = {'JPEG': 'image/jpeg', 'PNG': 'image/png',
                'GIF': 'image/gif', 'WEBP': 'image/webp'}
    mime = original_mime or mime_map.get(fmt, 'image/jpeg')

    buf = io.BytesIO()
    save_fmt = fmt if fmt in ('PNG', 'GIF', 'WEBP') else 'JPEG'
    pil_img.save(buf, format=save_fmt)
    return types.Part.from_bytes(data=buf.getvalue(), mime_type=mime)


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/fetch-blog-preview', methods=['POST'])
def fetch_blog_preview():
    data = request.get_json()
    blog_id = (data.get('blog_id') or '').strip()

    if not blog_id:
        return jsonify({'success': False, 'error': '블로그 ID를 입력해주세요.'})

    posts, error = fetch_naver_blog_posts(blog_id, count=10)

    if error:
        return jsonify({'success': False, 'error': error})

    return jsonify({
        'success': True,
        'posts': [{'title': p['title']} for p in posts[:3]],  # UI엔 3개만 미리보기
        'count': len(posts)
    })


@app.route('/api/generate', methods=['POST'])
def generate_post():
    try:
        client = get_client()

        blog_id = (request.form.get('blog_id') or '').strip()
        guide = (request.form.get('guide') or '').strip()

        try:
            keywords = json.loads(request.form.get('keywords') or '[]')
        except (json.JSONDecodeError, TypeError):
            keywords = []

        min_chars = 0
        try:
            min_chars = int(request.form.get('min_chars') or 0)
        except (ValueError, TypeError):
            min_chars = 0

        title_keywords_raw = (request.form.get('title_keywords') or '').strip()
        title_keywords = [k.strip() for k in re.split(r'[,，]', title_keywords_raw) if k.strip()]

        use_coupang = request.form.get('use_coupang') == 'true'
        coupang_count = max(1, min(5, int(request.form.get('coupang_count') or 2)))

        # 이미지 처리
        images = request.files.getlist('images')
        image_parts = []

        for img_file in images:
            if not img_file or not img_file.filename:
                continue
            img_data = img_file.read()
            if not img_data:
                continue
            pil_img = Image.open(io.BytesIO(img_data))
            mime = img_file.content_type or 'image/jpeg'
            image_parts.append(pil_to_part(pil_img, mime))

        if not image_parts:
            return jsonify({'success': False, 'error': '이미지를 1개 이상 업로드해주세요.'}), 400

        img_count = len(image_parts)

        # ── 1단계: 이미지 개별 분석 ──────────────────────────────────
        analysis_prompt = (
            f"총 {img_count}장의 이미지를 순서대로 각각 분석해주세요.\n"
            "아래 형식을 정확히 지켜주세요:\n\n"
        )
        for i in range(img_count):
            analysis_prompt += (
                f"[이미지 {i+1}]\n"
                f"내용: (이미지에 보이는 것을 구체적으로)\n"
                f"분위기: (색감, 느낌, 감성)\n"
                f"블로그 추천 내용: (이 이미지 옆에 자연스럽게 들어갈 내용)\n\n"
            )

        analysis_response = client.models.generate_content(
            model="gemini-2.5-flash-lite",
            config=types.GenerateContentConfig(
                system_instruction="이미지 분석 전문가입니다. 각 이미지를 정확하고 상세하게 분석합니다.",
                max_output_tokens=2048,
                temperature=0.3,
            ),
            contents=image_parts + [types.Part.from_text(text=analysis_prompt)],
        )
        image_analysis = analysis_response.text

        # ── 쿠팡 상품 검색 (이미지 분석 결과 기반) ───────────────────
        coupang_products = []
        if use_coupang:
            # 이미지 분석에서 검색 키워드 추출
            kw_prompt = (
                f"아래 이미지 분석 결과를 보고, 쿠팡에서 검색하면 좋을 상품 키워드를 {coupang_count}개 추출해주세요.\n"
                "키워드만 한 줄에 하나씩 출력하세요. 설명 없이 키워드만.\n\n"
                f"이미지 분석:\n{image_analysis}"
            )
            kw_response = client.models.generate_content(
                model="gemini-2.5-flash-lite",
                config=types.GenerateContentConfig(max_output_tokens=200, temperature=0.3),
                contents=[types.Part.from_text(text=kw_prompt)],
            )
            kw_lines = [l.strip().strip('-•').strip() for l in kw_response.text.strip().splitlines() if l.strip()]
            for kw in kw_lines[:coupang_count]:
                products = search_coupang_products(kw, limit=1)
                coupang_products.extend(products)

        # ── 블로그 스타일 참고 ────────────────────────────────────────
        style_posts = []
        style_error = None
        if blog_id:
            style_posts, style_error = fetch_naver_blog_posts(blog_id)

        # ── 2단계: 블로그 글 작성 ────────────────────────────────────
        img_labels = ', '.join(f'[이미지 {i+1}]' for i in range(img_count))
        sections = [
            f"아래 이미지 분석 결과와 원본 이미지들을 참고하여 네이버 블로그 글을 작성해주세요.\n\n"
            f"【이미지 분석 결과】\n{image_analysis}\n"
        ]

        if guide:
            sections.append(f"작성 가이드:\n{guide}\n")

        valid_kws = [kw for kw in keywords if kw.get('keyword') and kw.get('count')]
        if valid_kws:
            kw_lines = [f"'{kw['keyword']}': 최소 {kw['count']}번 포함" for kw in valid_kws]
            sections.append("필수 키워드 (반드시 포함):\n" + "\n".join(kw_lines) + "\n")

        if coupang_products:
            markers = ", ".join(f"[추천상품{i+1}]" for i in range(len(coupang_products)))
            product_desc = "\n".join(
                f"[추천상품{i+1}] → {p['name']} ({p['price']})"
                for i, p in enumerate(coupang_products)
            )
            sections.append(
                "【쿠팡 추천 상품 삽입 지침】\n"
                f"아래 상품 {len(coupang_products)}개를 글 내용과 자연스럽게 어울리는 위치에 각각 삽입하세요.\n"
                f"삽입할 때는 반드시 {markers} 마커를 단독 줄에 넣으세요. 다른 형식 사용 금지.\n\n"
                f"{product_desc}\n"
            )

        if style_posts:
            examples = []
            for i, post in enumerate(style_posts[:10], 1):
                examples.append(f"[참고 글 {i}] 제목: {post['title']}\n{post['content']}")
            style_block = "\n\n---\n\n".join(examples)
            sections.append(
                "【말투 & 문체 완벽 복사 지침】\n"
                "아래는 이 블로그 주인의 실제 글 10개입니다. 이 글들을 읽고 다음을 완벽히 파악하여 똑같이 흉내 내세요:\n\n"
                "1. 문장 종결 어미 패턴 (예: ~했어요, ~이에요, ~죠, ~랍니다 등)\n"
                "2. 문단 길이 — 짧게 자주 끊는지, 길게 이어 쓰는지\n"
                "3. 줄바꿈 빈도와 여백 스타일\n"
                "4. 이모지 사용 빈도와 위치\n"
                "5. 자주 쓰는 표현, 감탄사, 추임새\n"
                "6. 소제목 표현 방식\n"
                "7. 독자에게 말 걸듯 쓰는지, 혼자 일기 쓰듯 쓰는지\n\n"
                f"참고 글:\n\n{style_block[:5500]}\n"
            )

        sections.append(
            "작성 규칙:\n"
            f"- 이미지는 {img_count}장이며, 글 중간 중간 내용과 어울리는 자연스러운 위치에 {img_labels} 형식으로 정확히 삽입할 것\n"
            "- 이미지 태그는 반드시 단독 줄에 위치할 것 (예: 문단 끝에 줄바꿈 후 [이미지 1])\n"
            "- 마크다운 문법 절대 사용 금지: **, *, ##, ### 등 기호 사용하지 말 것\n"
            "- 불렛 포인트(- 또는 •)나 번호 목록 사용 금지\n"
            "- 소제목은 이모지와 함께 일반 텍스트로 작성 (예: 🍕 맛은 어땠을까?)\n"
            "- 친근하고 자연스러운 한국어 사용\n"
            + (f"- 공백 제외 글자수 {min_chars}자 이상 반드시 작성할 것\n" if min_chars > 0 else "- 1500~2500자 내외로 작성\n")
            + "- 필수 키워드는 자연스럽게 포함\n\n"
            + (
                f"글 작성이 끝나면 반드시 아래 형식을 그대로 붙여서 SEO 제목 3개를 추가할 것:\n"
                "===제목추천===\n"
                + (
                    f"※ 필수: 제목 3개 모두에 다음 키워드를 반드시 포함할 것 → {', '.join(title_keywords)}\n"
                    if title_keywords else ""
                )
                + "1. (검색 노출에 최적화된 제목, 30자 이내)\n"
                  "2. (궁금증이나 감성을 자극하는 제목, 30자 이내)\n"
                  "3. (장소/상품명 + 특징을 담은 구체적 제목, 30자 이내)\n"
                  "===끝==="
            )
        )

        prompt_text = "\n".join(sections)

        # 2단계: 이미지 + 분석결과 + 프롬프트 함께 전달
        contents = image_parts + [types.Part.from_text(text=prompt_text)]

        response = client.models.generate_content(
            model="gemini-2.5-flash-lite",
            config=types.GenerateContentConfig(
                system_instruction=(
                    "당신은 특정 블로거의 글쓰기 스타일을 완벽히 복제하는 전문가입니다.\n\n"
                    "절대 규칙:\n"
                    "- 마크다운 문법(**, *, ##, ---, ``` 등) 절대 사용 금지\n"
                    "- 불렛 포인트나 번호 목록 사용 금지\n"
                    "- 이미지 위치는 [이미지 N] 형식으로만 표시\n\n"
                    "스타일 복제 규칙:\n"
                    "- 참고 글의 문장 종결 어미를 그대로 따를 것\n"
                    "- 참고 글의 문단 길이와 줄바꿈 패턴을 그대로 따를 것\n"
                    "- 참고 글이 짧은 문단 위주라면 새 글도 짧게, 길면 길게\n"
                    "- 참고 글의 이모지 사용 빈도와 위치를 비슷하게 유지\n"
                    "- 참고 글에 없는 어색한 표현이나 문체는 사용 금지"
                ),
                max_output_tokens=4096,
                temperature=0.8,
            ),
            contents=contents,
        )

        generated_text = response.text

        # SEO 제목 파싱
        titles = []
        title_match = re.search(r'===제목추천===\n(.*?)===끝===', generated_text, re.DOTALL)
        if title_match:
            title_block = title_match.group(1)
            titles = re.findall(r'\d+\.\s*(.+)', title_block)
            titles = [t.strip() for t in titles[:3]]
            generated_text = generated_text[:title_match.start()].strip()

        # 마크다운 잔재 제거
        generated_text = re.sub(r'\*\*(.+?)\*\*', r'\1', generated_text)
        generated_text = re.sub(r'\*(.+?)\*', r'\1', generated_text)
        generated_text = re.sub(r'^#{1,6}\s+', '', generated_text, flags=re.MULTILINE)
        generated_text = re.sub(r'^[-*]\s+', '', generated_text, flags=re.MULTILINE)
        # [추천상품N] 마커를 실제 상품 카드 형식으로 교체
        for i, p in enumerate(coupang_products):
            marker = f"[추천상품{i+1}]"
            card = f"{{{{COUPANG:{p['name']}:{p['price']}:{p['url']}}}}}"
            generated_text = generated_text.replace(marker, card)

        generated_text = generated_text.strip()

        char_count = len(generated_text.replace('\n', '').replace(' ', ''))
        char_count_total = len(generated_text)

        # 키워드 충족 확인
        keyword_check = {}
        for kw in valid_kws:
            keyword = kw['keyword']
            required = int(kw['count'])
            actual = generated_text.count(keyword)
            keyword_check[keyword] = {
                'required': required,
                'actual': actual,
                'satisfied': actual >= required
            }

        return jsonify({
            'success': True,
            'post': generated_text,
            'image_analysis': image_analysis,
            'coupang_products': coupang_products,
            'titles': titles,
            'char_count': char_count,
            'char_count_total': char_count_total,
            'keyword_check': keyword_check,
            'style_error': style_error,
            'style_posts_count': len(style_posts)
        })

    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        return jsonify({'success': False, 'error': f'오류가 발생했습니다: {str(e)}'}), 500


if __name__ == '__main__':
    app.run(debug=True, port=5000)
