from flask import Flask, request, Response
import requests
import re
import json
import os
import time

app = Flask(__name__)


def extract_url(text):
    if not text:
        return None
    if text.strip().startswith('http'):
        return text.strip()
    url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
    urls = re.findall(url_pattern, text)
    if urls:
        return urls[0]
    return None


def parse_xiaohongshu(url):
    headers = {
        'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'zh-CN,zh;q=0.9',
        'Referer': 'https://www.xiaohongshu.com/',
    }

    try:
        session = requests.Session()
        resp = session.get(url, headers=headers, allow_redirects=True, timeout=15)
        html = resp.text
        final_url = resp.url

        note_id = None
        patterns = [
            r'/explore/([a-zA-Z0-9]+)',
            r'/discovery/item/([a-zA-Z0-9]+)',
            r'noteId["\']?\s*[:=]\s*["\']?([a-zA-Z0-9]+)',
            r'"noteId":"([a-zA-Z0-9]+)"',
        ]
        for p in patterns:
            m = re.search(p, final_url) or re.search(p, html)
            if m:
                note_id = m.group(1)
                break

        if not note_id:
            m = re.search(r'window\._SSR_HYDRATED_DATA\s*=\s*({.*?})<', html)
            if m:
                try:
                    data = json.loads(m.group(1))
                    note_id = list(data.get('note', {}).get('noteDetailMap', {}).keys())[0]
                except Exception:
                    pass

        if not note_id:
            return {'success': False, 'error': '无法提取笔记ID'}

        api_url = "https://edith.xiaohongshu.com/api/sns/web/v1/feed"
        payload = {
            "source_note_id": note_id,
            "image_formats": ["jpg", "webp", "avif"],
            "extra": {"need_body_topic": 1}
        }

        api_resp = session.post(api_url, json=payload, headers={
            **headers,
            'Content-Type': 'application/json;charset=UTF-8',
            'X-T': str(int(time.time() * 1000)),
        }, timeout=15)

        api_data = api_resp.json()

        if api_data.get('code') == 0 and api_data.get('data', {}).get('items'):
            note = api_data['data']['items'][0].get('note_card', {})
            tags = [t.get('name', '') for t in note.get('tag_list', []) if isinstance(t, dict)]
            return {
                'success': True,
                'title': note.get('title', ''),
                'content': note.get('desc', ''),
                'tags': '、'.join(tags),
                'author': note.get('user', {}).get('nickname', ''),
            }

        # 回退 HTML
        title_m = re.search(r'<title>(.*?)</title>', html)
        title = title_m.group(1).replace(' - 小红书', '').strip() if title_m else ''
        desc_m = re.search(r'<meta name="description" content="(.*?)">', html)
        desc = desc_m.group(1) if desc_m else ''

        return {
            'success': True,
            'title': title,
            'content': desc,
            'tags': '',
            'author': '',
        }

    except Exception as e:
        return {'success': False, 'error': str(e)}


def cors(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'POST, GET, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return response


@app.route('/parse', methods=['POST', 'OPTIONS'])
def parse():
    if request.method == 'OPTIONS':
        return cors(Response('', status=200))

    data = request.get_json()
    raw_url = data.get('url', '') if data else ''
    field = data.get('field', '')

    url = extract_url(raw_url)
    if not url:
        return cors(Response('ERROR: 无效网址', status=400, mimetype='text/plain; charset=utf-8'))

    result = parse_xiaohongshu(url)

    # 指定 field 时，返回纯文本（飞书 Text 模式直接用）
    if field:
        if not result.get('success'):
            return cors(Response('ERROR: ' + result.get('error', ''), status=500, mimetype='text/plain; charset=utf-8'))
        value = result.get(field, '')
        return cors(Response(str(value), status=200, mimetype='text/plain; charset=utf-8'))

    # 不指定 field，返回完整 JSON
    return cors(Response(json.dumps(result, ensure_ascii=False), status=200, mimetype='application/json; charset=utf-8'))


@app.route('/health', methods=['GET'])
def health():
    return cors(Response('{"status":"ok"}', status=200, mimetype='application/json'))


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
