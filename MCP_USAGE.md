# MCP Tools Usage Guide

This document describes how to use the MCP (Model Context Protocol) tools from the command line.

## Quick Start

### Setup Environment Variables

```bash
export PYTHONPATH="mcp/mcp_fs/src:mcp/mcp_pdf/src:mcp/mcp_comm/src"
export JOBSEARCH_HOME="$HOME/JobSearch"
```

### Basic Command Syntax

```bash
.venv/bin/python tools/mcp_call_fixed.py <server> <tool> '<json_arguments>'
```

Or use the wrapper script:

```bash
./mcp <server> <tool> '<json_arguments>'
```

## Available Servers and Tools

### 1. Filesystem Server (`fs`)

All file paths are relative to `$JOBSEARCH_HOME` (default: `~/JobSearch`).

#### List Directory Contents

```bash
./mcp fs fs.list '{"path":"."}'
./mcp fs fs.list '{"path":"notes"}'
./mcp fs fs.list '{"path":"exports"}'
```

**Parameters:**
- `path` (required): Directory path relative to JOBSEARCH_HOME

**Returns:**
```json
{
  "entries": [
    {
      "name": "file.txt",
      "path": "file.txt",
      "is_dir": false,
      "size": 1234,
      "modified": 1234567890.123
    }
  ]
}
```

#### Read File

```bash
./mcp fs fs.read '{"path":"notes/demo.txt"}'
```

**Parameters:**
- `path` (required): File path relative to JOBSEARCH_HOME

**Returns:**
```json
{
  "content": "file contents here"
}
```

#### Write File

```bash
./mcp fs fs.write '{"path":"notes/demo.txt","content":"Hello World","kind":"text"}'
```

For binary files (base64 encoded):
```bash
./mcp fs fs.write '{"path":"data.bin","content":"<base64-encoded-data>","kind":"binary"}'
```

**Parameters:**
- `path` (required): File path relative to JOBSEARCH_HOME
- `content` (required): File content (text or base64-encoded binary)
- `kind` (optional): `"text"` (default) or `"binary"`

**Returns:**
```json
{
  "path": "notes/demo.txt",
  "size": 11,
  "modified": 1234567890.123
}
```

### 2. PDF Server (`pdf`)

#### Render Markup to PDF

```bash
./mcp pdf pdf.render '{"markup":"# Title\n\nContent here"}'
```

**Parameters:**
- `markup` (required): Markdown/HTML content to render

**Returns:**
```json
{
  "path": "exports/export_20250101_120000.pdf"
}
```

The generated PDF is saved to `$JOBSEARCH_HOME/exports/`.

### 3. Communication Server (`comm`)

#### Send Email

```bash
./mcp comm email.send '{"to":"user@example.com","subject":"Test Subject","html":"<p>Email body</p>"}'
```

**Parameters:**
- `to` (required): Recipient email address
- `subject` (required): Email subject
- `html` (required): HTML email body

**Environment Variables Required:**
- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_USERNAME`
- `SMTP_PASSWORD`
- `SMTP_FROM`

**Returns:**
```json
{
  "status": "Email sent to user@example.com"
}
```

Note: If SMTP credentials are not configured, returns dry-run status.

#### Send Telegram Message

```bash
./mcp comm telegram.send '{"chat_id":"123456789","text":"Hello from CLI"}'
```

**Parameters:**
- `chat_id` (required): Telegram chat ID
- `text` (required): Message text

**Environment Variables Required:**
- `TELEGRAM_BOT_TOKEN`

**Returns:**
```json
{
  "status": "Telegram message sent to 123456789"
}
```

#### Send SMS

```bash
./mcp comm sms.send '{"to":"+15551234567","text":"Hello via SMS"}'
```

**Parameters:**
- `to` (required): Phone number in E.164 format (+country_code + number)
- `text` (required): SMS message text

**Environment Variables Required:**
- `TWILIO_ACCOUNT_SID`
- `TWILIO_AUTH_TOKEN`
- `TWILIO_FROM_NUMBER`

**Returns:**
```json
{
  "status": "SMS sent to +15551234567"
}
```

## JSON Escaping in Shell

### Option 1: Single Quotes (Recommended)

```bash
./mcp fs fs.write '{"path":"test.txt","content":"Hello"}'
```

### Option 2: Double Quotes with Escaping

```bash
./mcp fs fs.write "{\"path\":\"test.txt\",\"content\":\"Hello\"}"
```

### Option 3: Using Variables

```bash
JSON_ARGS='{"path":"test.txt","content":"Hello World"}'
./mcp fs fs.write "$JSON_ARGS"
```

## Creating Aliases

Add to your `~/.zshrc` or `~/.bashrc`:

```bash
# MCP tools alias
alias mcp='PYTHONPATH="mcp/mcp_fs/src:mcp/mcp_pdf/src:mcp/mcp_comm/src" JOBSEARCH_HOME="$HOME/JobSearch" .venv/bin/python tools/mcp_call_fixed.py'

# Server-specific aliases
alias mcp-fs='mcp fs'
alias mcp-pdf='mcp pdf'
alias mcp-comm='mcp comm'
```

Then reload your shell:
```bash
source ~/.zshrc  # or ~/.bashrc
```

Usage after aliasing:
```bash
mcp-fs fs.list '{"path":"."}'
mcp-fs fs.write '{"path":"notes/test.txt","content":"Hello"}'
mcp-pdf pdf.render '{"markup":"# Test"}'
```

## Examples

### Example 1: Create a File and List Directory

```bash
# Write a file
./mcp fs fs.write '{"path":"notes/example.txt","content":"This is an example file","kind":"text"}'

# List the directory
./mcp fs fs.list '{"path":"notes"}'

# Read the file back
./mcp fs fs.read '{"path":"notes/example.txt"}'
```

### Example 2: Generate a PDF Report

```bash
./mcp pdf pdf.render '{"markup":"# Report\n\n## Section 1\n\nContent here\n\n## Section 2\n\nMore content"}'
```

### Example 3: Send Notifications

```bash
# Send email
./mcp comm email.send '{"to":"team@example.com","subject":"Daily Report","html":"<h1>Report</h1><p>All systems operational</p>"}'

# Send Telegram
./mcp comm telegram.send '{"chat_id":"123456789","text":"Deployment completed successfully"}'
```

## Troubleshooting

### Command Hangs Indefinitely

If you're using the original `tools/mcp_call.py` and it hangs, use `tools/mcp_call_fixed.py` instead, which bypasses a concurrency issue in the MCP SDK.

### "Module not found" Errors

Ensure `PYTHONPATH` is set correctly:
```bash
export PYTHONPATH="mcp/mcp_fs/src:mcp/mcp_pdf/src:mcp/mcp_comm/src"
```

### "JOBSEARCH_HOME environment variable is required"

Set the JOBSEARCH_HOME variable:
```bash
export JOBSEARCH_HOME="$HOME/JobSearch"
```

Or create the directory if it doesn't exist:
```bash
mkdir -p ~/JobSearch
```

### File Not Found or Path Errors

Remember that all paths in the `fs` server are relative to `$JOBSEARCH_HOME`. If `JOBSEARCH_HOME="~/JobSearch"`, then:
- `{"path":"notes/file.txt"}` → `~/JobSearch/notes/file.txt`
- `{"path":"file.txt"}` → `~/JobSearch/file.txt`

## Programmatic Usage (Python)

You can also call the tools from Python:

```python
from tools.mcp_call_fixed import call_tool_sync

# List files
result = call_tool_sync("fs", "fs.list", {"path": "."})
print(result)

# Write file
result = call_tool_sync("fs", "fs.write", {
    "path": "notes/test.txt",
    "content": "Hello from Python",
    "kind": "text"
})
print(result)

# Generate PDF
result = call_tool_sync("pdf", "pdf.render", {
    "markup": "# My Document\n\nContent here"
})
print(result)
```

## Integration with LLMs

When using these tools in an LLM context (e.g., Claude, GPT), you can invoke them as:

```python
import subprocess
import json

def call_mcp_tool(server: str, tool: str, arguments: dict) -> dict:
    """Call an MCP tool and return the result."""
    cmd = [
        ".venv/bin/python",
        "tools/mcp_call_fixed.py",
        server,
        tool,
        json.dumps(arguments)
    ]

    env = {
        **os.environ,
        "PYTHONPATH": "mcp/mcp_fs/src:mcp/mcp_pdf/src:mcp/mcp_comm/src",
        "JOBSEARCH_HOME": os.path.expanduser("~/JobSearch")
    }

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env=env
    )

    if result.returncode != 0:
        raise RuntimeError(f"MCP tool failed: {result.stderr}")

    return json.loads(result.stdout)
```

## Security Notes

- The `fs` server restricts all operations to within `$JOBSEARCH_HOME` for security
- Paths attempting to escape this directory (e.g., `../../../etc/passwd`) will be rejected
- Communication tools (email, SMS, Telegram) require proper credentials and should be used carefully
- Never commit credentials to version control - use environment variables

## Technical Details

### Why `mcp_call_fixed.py`?

The original `mcp_call.py` uses the MCP Python SDK's `stdio_client`, which has a concurrency bug with unbuffered memory streams that causes deadlocks. The `mcp_call_fixed.py` implementation uses direct subprocess communication to avoid this issue.

### MCP Protocol

The tools use the Model Context Protocol (MCP) for client-server communication:
1. Client sends `initialize` request
2. Server responds with capabilities
3. Client sends `notifications/initialized`
4. Client sends tool call requests (e.g., `tools/call`)
5. Server responds with results

All communication happens over JSON-RPC via stdin/stdout.
