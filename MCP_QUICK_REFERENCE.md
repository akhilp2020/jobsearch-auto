# MCP Tools - Quick Reference Card

## Usage

```bash
./mcp-cli <server> <tool> '<json_arguments>'
```

## Filesystem (`fs`)

```bash
# List directory
./mcp-cli fs fs.list '{"path":"."}'

# Read file
./mcp-cli fs fs.read '{"path":"notes/file.txt"}'

# Write file
./mcp-cli fs fs.write '{"path":"notes/file.txt","content":"Hello","kind":"text"}'
```

## PDF (`pdf`)

```bash
# Generate PDF from markdown
./mcp-cli pdf pdf.render '{"markup":"# Title\n\nContent"}'
```

## Communication (`comm`)

```bash
# Send email
./mcp-cli comm email.send '{"to":"user@example.com","subject":"Subject","html":"<p>Body</p>"}'

# Send Telegram
./mcp-cli comm telegram.send '{"chat_id":"123456","text":"Message"}'

# Send SMS
./mcp-cli comm sms.send '{"to":"+15551234567","text":"Message"}'
```

## Environment

```bash
export JOBSEARCH_HOME="$HOME/JobSearch"  # Optional, defaults to ~/JobSearch
```

## Full Documentation

See [MCP_USAGE.md](./MCP_USAGE.md) for complete documentation.
