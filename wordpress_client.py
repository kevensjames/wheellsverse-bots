import requests

BASE_URL = "http://host.docker.internal:8000/wp-json/wp/v2"


def get_posts():
    res = requests.get(f"{BASE_URL}/posts")
    if res.status_code == 200:
        return res.json()
    return []


def create_post(title, content, token=None):
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    data = {
        "title": title,
        "content": content,
        "status": "publish"
    }

    res = requests.post(f"{BASE_URL}/posts", json=data, headers=headers)
    return res.status_code, res.text
