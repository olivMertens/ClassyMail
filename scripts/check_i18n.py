import json
import os
import sys

def flatten_json(y):
    out = {}
    def flatten(x, name=''):
        if type(x) is dict:
            for a in x:
                flatten(x[a], name + a + '.')
        else:
            out[name[:-1]] = x
    flatten(y)
    return out

def main():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    locales_dir = os.path.join(base_dir, 'frontend', 'src', 'locales')

    en_path = os.path.join(locales_dir, 'en.json')
    fr_path = os.path.join(locales_dir, 'fr.json')

    try:
        with open(en_path, 'r', encoding='utf-8') as f:
            en_data = json.load(f)
        with open(fr_path, 'r', encoding='utf-8') as f:
            fr_data = json.load(f)
    except FileNotFoundError as e:
        print(f"Error loading locale files: {e}")
        sys.exit(1)

    en_keys = set(flatten_json(en_data).keys())
    fr_keys = set(flatten_json(fr_data).keys())

    missing_in_fr = en_keys - fr_keys
    missing_in_en = fr_keys - en_keys

    if not missing_in_fr and not missing_in_en:
        print("✅ SUCCESS: Locale files are synchronized.")
        sys.exit(0)

    if missing_in_fr:
        print(f"❌ ERROR: Missing keys in fr.json ({len(missing_in_fr)}):")
        for k in sorted(missing_in_fr):
            print(f"  - {k}")

    if missing_in_en:
        print(f"❌ ERROR: Missing keys in en.json ({len(missing_in_en)}):")
        for k in sorted(missing_in_en):
            print(f"  - {k}")

    sys.exit(1)

if __name__ == "__main__":
    main()
