from flask import Flask, request, jsonify
import requests
import re
import json
import os

app = Flask(__name__)

def extract_url(text):
    """从任何文本中提取网址"""
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

        # 提取 note_id
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
                except:
                    pass

        if not note_id:
            return {'success': False, 'error': '无法提取笔记ID，请检查链接'}

        # 调用小红书 API
        api_url = "https://edith.xiaohongshu.com/api/sns/web/v1/feed"
        payload = {
            "source_note_id": note_id,
            "image_formats": ["jpg", "webp", "avif"],
            "extra": {"need_body_topic": 1}
        }

        api_resp = session.post(api_url, json=payload, headers={
            **headers,
            'Content-Type': 'application/json;charset=UTF-8',
            'X-T': str(int(__import__('time').time() * 1000)),
        }, timeout=15)

        api_data = api_resp.json()

        if api_data.get('code') == 0 and api_data.get('data', {}).get('items'):
            note = api_data['data']['items'][0].get('note_card', {})
            tags = [t.get('name', '') for t in note.get('tag_list', []) if isinstance(t, dict)]
            return {
                'success': True,
                'note_id': note_id,
                'title': note.get('title', ''),
                'content': note.get('desc', ''),
                'tags': '、'.join(tags),   # 直接拼接为字符串
                'author': note.get('user', {}).get('nickname', ''),
                'likes': str(note.get('interact_info', {}).get('liked_count', 0)),
                'collects': str(note.get('interact_info', {}).get('collected_count', 0)),
            }

        # API 失败，回退到 HTML 提取
        title_m = re.search(r'<title>(.*?)</title>', html)
        title = title_m.group(1).replace(' - 小红书', '').strip() if title_m else ''
        desc_m = re.search(r'<meta name="description" content="(.*?)">', html)
        desc = desc_m.group(1) if desc_m else ''

        return {
            'success': True,
            'note_id': note_id,
            'title': title,
            'content': desc,
            'tags': '',
            'author': '',
            'source': 'html_fallback',
            'warning': 'API受限，仅从页面提取了基础信息'
        }

    except Exception as e:
        return {'success': False, 'error': f'解析异常: {str(e)}'}


def make_cors_response(text_or_json, is_text=False, status=200):
    """统一处理 CORS 响应头"""
    if is_text:
        resp = app.make_response((str(text_or_json), status))
        resp.headers['Content-Type'] = 'text/plain; charset=utf-8'
    else:
        resp = app.make_response((json.dumps(text_or_json, ensure_ascii=False), status))
        resp.headers['Content-Type'] = 'application/json; charset=utf-8'
    resp.headers['Access-Control-Allow-Origin'] = '*'
    resp.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
    resp.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return resp


@app.route('/parse', methods=['POST', 'OPTIONS'])
def parse():
    # 处理预检请求
    if request.method == 'OPTIONS':
        return make_cors_response('', is_text=True)

    data = request.get_json()
    raw_url = data.get('url', '') if data else ''
    field = data.get('field', '')  # 可选：title / content / tags / author

    url = extract_url(raw_url)
    if not url:
        return make_cors_response({'success': False, 'error': '无法从输入中提取有效网址'}, status=400)

    result = parse_xiaohongshu(url)

    # ✅ 如果指定了 field，直接返回纯文本（飞书自动化可直接用 body）
  if field:
        if not result.get('success'):
            return make_cors_response({'value': '', 'error': result.get('error', '')}, status=500)
        value = result.get(field, '')
        if isinstance(value, list):
            value = '、'.join(value)
        return make_cors_response({'value': str(value)})

    # 未指定 field，返回完整 JSON
    return make_cors_response(result)


@app.route('/health', methods=['GET'])
def health():
    """健康检查，防止 Render 休眠"""
    return make_cors_response({'status': 'ok'})


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
