"""
inject_widget.py — Auto-add chatbot widget to ALL HTML pages in a folder

Usage:
  python inject_widget.py <path_to_website_folder> <client_id> <api_key>

Example:
  python inject_widget.py "test_website/e-commerce_fashion" 9893a465-... your-api-key

This adds the chatbot script tag before </body> on every .html file.
Safe to run multiple times — won't add the script twice.
"""
import sys, os, re
from pathlib import Path

if len(sys.argv) < 4:
    print("\nUsage: python inject_widget.py <website_folder> <client_id> <api_key>\n")
    print("Example:")
    print('  python inject_widget.py "test_website/e-commerce_fashion" 9893a465-1be3-4685-9482-d9b995ce9ce0 your-api-key\n')
    sys.exit(1)

folder    = Path(sys.argv[1])
client_id = sys.argv[2]
api_key   = sys.argv[3]

if not folder.exists():
    print(f"ERROR: folder not found: {folder}")
    sys.exit(1)

SCRIPT_TAG = f'''
    <!-- ChatBot Widget -->
    <script
      src="http://localhost:8000/widget/chatbot.js"
      data-client-id="{client_id}"
      data-api-key="{api_key}"
      defer>
    </script>'''

html_files = list(folder.glob("**/*.html"))
if not html_files:
    print(f"No .html files found in {folder}")
    sys.exit(1)

print(f"\nFound {len(html_files)} HTML files in {folder}\n")

injected = 0
skipped  = 0

for f in sorted(html_files):
    content = f.read_text(encoding="utf-8", errors="ignore")
    
    # Skip if already has widget
    if 'data-client-id' in content or 'chatbot.js' in content:
        print(f"  SKIP (already has widget): {f.name}")
        skipped += 1
        continue
    
    # Inject before </body>
    if "</body>" in content.lower():
        # Case-insensitive replace
        new_content = re.sub(r'</body>', SCRIPT_TAG + '\n</body>', content, flags=re.IGNORECASE, count=1)
        f.write_text(new_content, encoding="utf-8")
        print(f"  ✓ Injected: {f.name}")
        injected += 1
    else:
        # No </body> tag — append at end
        content += SCRIPT_TAG
        f.write_text(content, encoding="utf-8")
        print(f"  ✓ Appended: {f.name}")
        injected += 1

print(f"""
Done!
  Injected : {injected} files
  Skipped  : {skipped} files (already had widget)

Now refresh your browser and navigate between pages —
the chat history will persist across all pages.
""")
