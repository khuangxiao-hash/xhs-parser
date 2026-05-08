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
            return {'success': False, 'title': '', 'content': '', 'tags': '', 'author': '', 'error': '无法提取笔记ID'}

        # 方法1: 从 SSR 数据中提取（最准确）
        ssr_patterns = [
            r'window\.__INITIAL_STATE__\s*=\s*({.*?})\s*</script>',
            r'window\.__pinia\s*=\s*({.*?})\s*</script>',
        ]
        for sp in ssr_patterns:
            ssr_match = re.search(sp, html, re.DOTALL)
            if ssr_match:
                try:
                    ssr_data = json.loads(ssr_match.group(1))
                    # 尝试找到 note 详情
                    note_map = (ssr_data.get('note', {}) or {}).get('noteDetailMap', {}) or {}
                    note_detail = note_map.get(note_id, {}).get('note', {})
                    if note_detail:
                        tags_list = [t.get('name', '') for t in note_detail.get('tagList', []) if isinstance(t, dict)]
                        desc = note_detail.get('desc', '')
                        tags = '、'.join(tags_list) if tags_list else extract_tags_from_text(desc)
                        author = note_detail.get('user', {}).get('nickname', '')
                        return {
                            'success': True,
                            'title': note_detail.get('title', ''),
                            'content': desc,
                            'tags': tags,
                            'author': author,
                            'error': ''
                        }
                except Exception:
                    pass

        # 方法2: 从 HTML 中精准定位作者（找笔记作者，不是登录用户）
        # 小红书 HTML 里笔记作者通常在 noteCard 或 note-detail 附近
        author = ''

        # 尝试找 noteCard 区域内的 nickname
        note_section_match = re.search(
            r'"noteId"\s*:\s*"' + note_id + r'".*?"nickname"\s*:\s*"([^"]+)"',
            html, re.DOTALL
        )
        if note_section_match:
            author = note_section_match.group(1)

        # 备用：找 note_card 里的 user nickname
        if not author:
            user_block_match = re.search(
                r'"note_card".*?"user".*?"nickname"\s*:\s*"([^"]+)"',
                html, re.DOTALL
            )
            if user_block_match:
                author = user_block_match.group(1)

        # 备用：og:title 有时含作者信息
        if not author:
            og_match = re.search(r'<meta property="og:title" content="([^"]+)"', html)
            if og_match:
                og_title = og_match.group(1)
                # og:title 格式通常是 "标题 - 作者 的小红书"
                author_m = re.search(r'-\s*(.+?)\s*的小红书', og_title)
                if author_m:
                    author = author_m.group(1)

        # 提取标题
        title_m = re.search(r'<title>(.*?)</title>', html)
        title = title_m.group(1).replace(' - 小红书', '').strip() if title_m else ''

        # 提取正文
        desc_m = re.search(r'<meta name="description" content="(.*?)"', html)
        desc = desc_m.group(1) if desc_m else ''

        # 从正文提取标签
        tags = extract_tags_from_text(desc)

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
