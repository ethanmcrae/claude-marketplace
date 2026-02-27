# /claude-usage — Check Usage Limits

Fetch and display current claude.ai usage limits.

## Flow

1. **Fetch and display usage.** Run this inline Python snippet:

   ```bash
   python3 -c "
   import sys
   sys.path.insert(0, '<project_root>')

   from lib.session import load_credentials, SessionFileNotFound, SessionExpired, SessionInvalid
   from lib.client import AuthenticationError, NetworkError
   from lib.usage import fetch_usage, load_cached_usage, format_summary, CacheError

   try:
       creds = load_credentials()
       report = fetch_usage(creds)
       print(format_summary(report))
   except SessionFileNotFound:
       print('No credentials found. Run /claude-usage-init to set up.')
       sys.exit(1)
   except (SessionExpired, AuthenticationError):
       print('Credentials expired. Run /claude-usage-init to re-authenticate.')
       sys.exit(1)
   except NetworkError as e:
       print(f'Network error: {e}')
       print('Attempting to load cached data...')
       try:
           report = load_cached_usage()
           print(format_summary(report))
           print(f'\n(Cached from {report.fetched_at:%Y-%m-%d %H:%M} UTC)')
       except CacheError:
           print('No cached data available.')
       sys.exit(1)
   except Exception as e:
       print(f'Error: {e}')
       sys.exit(1)
   "
   ```

   Replace `<project_root>` with the absolute path to this project's root directory.

2. **Show the output directly.** The script prints a formatted summary — display it to the user as-is. Do not reformat or paraphrase it.

## Important

- This is a quick status check. Do not add commentary beyond what the script outputs.
- If the script shows a "Run /claude-usage-init" message, offer to run that skill for the user.
- The script updates the cache file (`~/.claude/claude-usage/cache.json`) as a side effect, keeping the menu bar widget fresh.
