import httpx
import sys

def main():
    url = 'http://127.0.0.1:8011/api/admin/test-mistral-ocr'
    try:
        r = httpx.get(url, timeout=60)
        print(r.status_code)
        print(r.text)
    except Exception as e:
        print('ERROR', e)
        sys.exit(1)

if __name__ == '__main__':
    main()
