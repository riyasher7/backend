"""Simple script to POST to your campaign send endpoint.
Requires: pip install requests
Usage: python send_trigger.py --campaign <campaign-id> --host http://127.0.0.1:8000
"""
import argparse
import requests

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--campaign', required=True, help='Campaign id to trigger')
    p.add_argument('--host', default='http://127.0.0.1:9100', help='API base URL')
    args = p.parse_args()

    url = args.host.rstrip('/') + f'/campaigns/{args.campaign}/send'
    try:
        r = requests.post(url)
        print('Status:', r.status_code)
        print('Response:', r.text)
    except Exception as e:
        print('Request failed:', e)
