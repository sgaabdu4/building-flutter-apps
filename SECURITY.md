# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 3.0.x   | :white_check_mark: |
| < 3.0   | :x:                |

## Reporting a Vulnerability

If you discover a security vulnerability in this skill, please report it responsibly:

1. **Do NOT open a public issue** for security vulnerabilities
2. Email security concerns to the repository owner
3. Include:
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact
   - Suggested fix (if any)

### Response Timeline

- **Acknowledgment**: Within 48 hours
- **Initial Assessment**: Within 7 days
- **Resolution**: Depends on severity

### What to Expect

- We take all security reports seriously
- We will investigate and respond promptly
- We will credit reporters in our changelog (unless you prefer anonymity)

## Security Best Practices for Users

When using this skill:

1. **Never commit secrets** - Use environment variables for API keys
2. **Review generated code** - Always review code suggestions before running
3. **Keep dependencies updated** - Run `flutter pub upgrade` regularly
4. **Validate user input** - Always validate form inputs as shown in patterns
5. **Use secure storage** - Use `flutter_secure_storage` for sensitive data

## Scope

This security policy applies to the skill documentation and any included code examples. The policy does not cover:

- Third-party dependencies (Riverpod, Freezed, GoRouter, etc.)
- The Flutter framework itself
- Your implementation of the patterns described
