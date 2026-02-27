# /claude-usage-init — First-Time Setup

Set up claude-usage by validating the user's claude.ai session cookie.

## Flow

1. **Ask for the sessionKey.** Tell the user:

   > I need your claude.ai sessionKey cookie to set up usage tracking.
   >
   > To find it:
   > 1. Open **claude.ai** in your browser and make sure you're logged in
   > 2. Open DevTools (Cmd+Option+I on Mac)
   > 3. Go to **Application** → **Cookies** → `https://claude.ai`
   > 4. Find the row named `sessionKey`
   > 5. Double-click the **Value** cell and copy the entire value
   >
   > Paste your sessionKey here.

2. **Validate and save.** Once the user provides their key, run the init script:

   ```bash
   python3 -c "
   import json, sys
   sys.path.insert(0, '<project_root>')
   from lib.init import validate_and_save
   result = validate_and_save('''<SESSION_KEY>''')
   print(json.dumps(result, indent=2))
   "
   ```

   Replace `<project_root>` with the absolute path to this project's root directory.
   Replace `<SESSION_KEY>` with the user's pasted value (be careful with quotes — use triple-quotes).

3. **Report the result:**
   - **Success:** Tell the user their email and that setup is complete. They can now use `/claude-usage` to check their limits.
   - **InvalidSessionKey:** Tell the user their key was rejected — it may be expired or copied incorrectly. Ask them to try again.
   - **Network/other error:** Show the error message and suggest retrying.

## Important

- The sessionKey is sensitive — do NOT echo it back to the user or log it in full.
- The session file is written to `~/.claude/claude-usage/claude-ai-session.json`.
- sessionKeys last ~28 days. Users only need to re-run this when their key expires.
- This skill only supports email/password claude.ai accounts. OAuth users need a different setup path.
