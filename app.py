from flask import Flask, request, jsonify
import requests
import re
import json

app = Flask(__name__)

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
        
        # 尝试从页面初始数据提取
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
                'tags': tags,
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
            'tags': [],
            'author': '',
            'source': 'html_fallback',
            'warning': 'API受限，仅从页面提取了基础信息'
        }
        
    except Exception as e:
        return {'success': False, 'error': f'解析异常: {str(e)}'}

@app.route('/parse', methods=['POST', 'OPTIONS'])
def parse():
    if request.method == 'OPTIONS':
        return jsonify({}), 200, {
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'POST, OPTIONS',
            'Access-Control-Allow-Headers': 'Content-Type',
        }
    
    data = request.get_json()
    url = data.get('url', '') if data else ''
    
    if not url:
        return jsonify({'success': False, 'error': '缺少url参数'}), 400
    
    result = parse_xiaohongshu(url)
    response = jsonify(result)
    response.headers.add('Access-Control-Allow-Origin', '*')
    return response

if __name__ == '__main__':
    import os
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
