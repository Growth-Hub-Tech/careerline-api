# Conventional Commits

This project enforces conventional commit messages using commitlint.

## Commit Message Format

Each commit message must follow this format:

```
<type>(<optional scope>): <subject>

<optional body>

<optional footer>
```

### Types

The following commit types are allowed:

- **feat**: A new feature
- **fix**: A bug fix
- **docs**: Documentation only changes
- **style**: Changes that don't affect the meaning of the code (white-space, formatting, etc.)
- **refactor**: A code change that neither fixes a bug nor adds a feature
- **perf**: A code change that improves performance
- **test**: Adding missing tests or correcting existing tests
- **build**: Changes that affect the build system or external dependencies
- **ci**: Changes to CI configuration files and scripts
- **chore**: Other changes that don't modify src or test files
- **revert**: Reverts a previous commit

### Examples

✅ **Valid commit messages:**

```
feat: add user authentication
fix: resolve login button crash
refactor: simplify validation logic
docs: update API documentation
style: format code with prettier
```

❌ **Invalid commit messages:**

```
Added new feature          # Missing type
feat add user auth         # Missing colon
FEAT: new feature          # Type must be lowercase
feat: Added new feature.   # Subject should not end with period
```

### Rules

- Type must be one of the allowed types above
- Type must be in lowercase
- Subject is required and cannot be empty
- Subject must not end with a period
- Header (type + subject) must not exceed 100 characters

## Enforcement

Commit messages are automatically validated on commit via Husky's `commit-msg` hook. If your commit message doesn't follow the conventional format, the commit will be rejected.
