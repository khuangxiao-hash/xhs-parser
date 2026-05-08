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
    # 从环境变量读取 Cookie
    cookie = os.environ.get('XHS_COOKIE', '')

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'zh-CN,zh;q=0.9',
        'Referer': 'https://www.xiaohongshu.com/',
        'Cookie': cookie,
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
            return {'success': False, 'title': '', 'content': '', 'tags': '', 'author': '', 'error': '无法提取笔记ID'}

        api_url = "https://edith.xiaohongshu.com/api/sns/web/v1/feed"
        payload = {
            "source_note_id": note_id,
            "image_formats": ["jpg", "webp", "avif"],
            "extra": {"need_body_topic": 1}
        }

        api_headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Content-Type': 'application/json;charset=UTF-8',
            'Referer': 'https://www.xiaohongshu.com/',
            'Origin': 'https://www.xiaohongshu.com',
            'Cookie': cookie,
            'X-T': str(int(time.time() * 1000)),
        }

        api_resp = session.post(api_url, json=payload, headers=api_headers, timeout=15)
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
                'error': ''
            }

        # 回退：从 HTML 提取
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
            'error': f'API返回码:{api_data.get("code")}，已回退HTML提取'
        }

    except Exception as e:
        return {'success': False, 'title': '', 'content': '', 'tags': '', 'author': '', 'error': str(e)}


def make_json_response(data, status=200):
    resp = Response(
        json.dumps(data, ensure_ascii=False),
        status=status,
        mimetype='application/json; charset=utf-8'
    )
    resp.headers['Access-Control-Allow-Origin'] = '*'
    resp.headers['Access-Control-Allow-Methods'] = 'POST, GET, OPTIONS'
    resp.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return resp


@app.route('/parse', methods=['POST', 'OPTIONS'])
def parse():
    if request.method == 'OPTIONS':
        return make_json_response({})

    data = request.get_json()
    raw_url = data.get('url', '') if data else ''

    url = extract_url(raw_url)
    if not url:
        return make_json_response({'success': False, 'title': '', 'content': '', 'tags': '', 'author': '', 'error': '无效网址'}, status=400)

    result = parse_xiaohongshu(url)
    return make_json_response(result)


@app.route('/health', methods=['GET'])
def health():
    return make_json_response({'status': 'ok'})


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
