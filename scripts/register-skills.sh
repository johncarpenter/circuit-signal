#!/bin/bash
# Register skills and agents with Claude Code SDK's native discovery.
#
# The SDK discovers:
#   - Slash commands from .claude/commands/{name}.md
#   - Skills (auto-invoked) from .claude/skills/{name}/SKILL.md
#   - Agents from .claude/agents/{name}.md
#
# This script symlinks from the app source into the workspace .claude/ directory
# so the SDK can discover them at runtime.

set -euo pipefail

APP_DIR="${APP_DIR:-/opt/agent}"
WORKSPACE="${WORKSPACE_PATH:-/workspace}"
COMMANDS_DIR="${WORKSPACE}/.claude/commands"
SDK_SKILLS_DIR="${WORKSPACE}/.claude/skills"
AGENTS_DIR="${WORKSPACE}/.claude/agents"

echo "Registering skills from ${APP_DIR}/.claude/ into ${WORKSPACE}/.claude/"

# Clean previous registrations
rm -rf "${COMMANDS_DIR}" "${SDK_SKILLS_DIR}" "${AGENTS_DIR}"
mkdir -p "${COMMANDS_DIR}" "${SDK_SKILLS_DIR}" "${AGENTS_DIR}"

# --- Skills ---

skill_count=0

if [ -d "${APP_DIR}/.claude/skills" ]; then
    while IFS= read -r skill_md; do
        rel="${skill_md#${APP_DIR}/.claude/skills/}"
        dir="$(dirname "${rel}")"
        name="$(basename "${dir}")"

        # Register as slash command
        ln -sf "${skill_md}" "${COMMANDS_DIR}/${name}.md"

        # Register as SDK skill
        mkdir -p "${SDK_SKILLS_DIR}/${name}"
        ln -sf "${skill_md}" "${SDK_SKILLS_DIR}/${name}/SKILL.md"

        skill_count=$((skill_count + 1))
    done < <(find "${APP_DIR}/.claude/skills" -name "SKILL.md" -type f | sort)
fi

echo "Registered ${skill_count} skills"

# --- Slash Commands ---

cmd_count=0

if [ -d "${APP_DIR}/.claude/commands" ]; then
    while IFS= read -r cmd_md; do
        name="$(basename "${cmd_md}")"
        ln -sf "${cmd_md}" "${COMMANDS_DIR}/${name}"
        cmd_count=$((cmd_count + 1))
    done < <(find "${APP_DIR}/.claude/commands" -name "*.md" -type f | sort)
fi

echo "Registered ${cmd_count} slash commands"

# --- Agents ---

agent_count=0

if [ -d "${APP_DIR}/.claude/agents" ]; then
    while IFS= read -r agent_md; do
        name="$(basename "${agent_md}")"
        ln -sf "${agent_md}" "${AGENTS_DIR}/${name}"
        agent_count=$((agent_count + 1))
    done < <(find "${APP_DIR}/.claude/agents" -maxdepth 1 -name "*.md" -type f | sort)
fi

echo "Registered ${agent_count} agents"

# --- Copy settings if present ---

if [ -f "${APP_DIR}/.claude/settings.local.json" ]; then
    cp "${APP_DIR}/.claude/settings.local.json" "${WORKSPACE}/.claude/settings.local.json"
    echo "Copied settings.local.json"
fi

echo "Registration complete: ${skill_count} skills, ${cmd_count} commands, ${agent_count} agents"
