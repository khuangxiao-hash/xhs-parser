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


def extract_tags_from_text(text):
    """从文本中提取 #标签"""
    tags = re.findall(r'#([^\s#，,。！!？?、]+)', text)
    return '、'.join(tags) if tags else ''


def parse_xiaohongshu(url):
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

        # 尝试从 HTML 的 SSR 数据提取完整信息
        ssr_match = re.search(r'window\.__INITIAL_STATE__\s*=\s*({.*?})\s*</script>', html, re.DOTALL)
        if ssr_match:
            try:
                ssr_data = json.loads(ssr_match.group(1))
                note_detail = ssr_data.get('note', {}).get('noteDetailMap', {}).get(note_id, {}).get('note', {})
                if note_detail:
                    tags = [t.get('name', '') for t in note_detail.get('tagList', []) if isinstance(t, dict)]
                    desc = note_detail.get('desc', '')
                    if not tags:
                        tags_from_desc = extract_tags_from_text(desc)
                    else:
                        tags_from_desc = '、'.join(tags)
                    return {
                        'success': True,
                        'title': note_detail.get('title', ''),
                        'content': desc,
                        'tags': tags_from_desc,
                        'author': note_detail.get('user', {}).get('nickname', ''),
                        'error': ''
                    }
            except Exception:
                pass

        # 回退：从 HTML meta 标签提取
        title_m = re.search(r'<title>(.*?)</title>', html)
        title = title_m.group(1).replace(' - 小红书', '').strip() if title_m else ''

        # 提取 description
        desc_m = re.search(r'<meta name="description" content="(.*?)"', html)
        desc = desc_m.group(1) if desc_m else ''

        # 从 description 提取标签
        tags = extract_tags_from_text(desc)

        # 提取作者：从多个位置尝试
        author = ''
        author_patterns = [
            r'"nickname"\s*:\s*"([^"]+)"',
            r'"author"\s*:\s*"([^"]+)"',
            r'<meta name="author" content="([^"]+)"',
        ]
        for ap in author_patterns:
            am = re.search(ap, html)
            if am:
                author = am.group(1)
                break

        return {
            'success': True,
            'title': title,
            'content': desc,
            'tags': tags,
            'author': author,
            'error': 'HTML提取模式'
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
