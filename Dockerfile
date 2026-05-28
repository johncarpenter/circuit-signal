FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

# System packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    gnupg \
    python3.12 \
    python3.12-venv \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Node.js 22.x (required by Claude Code CLI)
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Claude Code CLI
RUN npm install -g @anthropic-ai/claude-code

# uv (required for MCP server venvs and core packages)
RUN pip install --no-cache-dir --break-system-packages uv

# Create non-root user
RUN groupadd -g 1001 agent && \
    useradd -u 1001 -g agent -m -s /bin/bash agent

# App directory
WORKDIR /opt/agent

# Python dependencies (FastAPI layer)
COPY requirements.txt .
RUN pip install --no-cache-dir --break-system-packages -r requirements.txt

# Copy application code
COPY app/ app/
COPY mcp/ mcp/
COPY tdv_profiler/ tdv_profiler/
COPY data_prep/ data_prep/
COPY batch_runner/ batch_runner/
COPY .mcp.json .
COPY .claude/ .claude/
COPY scripts/ scripts/
COPY templates/ templates/

# Create Linux venvs for MCP servers
RUN for d in mcp/layer0 mcp/layer1 mcp/layer2 mcp/query-planner; do \
        if [ -f "$d/pyproject.toml" ]; then \
            echo "Installing $d..." && uv sync --directory "$d" || true; \
        fi; \
    done

# Install core packages into system Python (needed by FastAPI pipeline service).
# Order matters: pip doesn't understand uv.sources, so we install leaves first.
# 1) tdv_profiler, mcp/layer0, mcp/layer1 have no local deps
# 2) data_prep depends on tdv-profiler
# 3) batch_runner depends on data-loader-mcp, signal-discovery-mcp, data-prep
RUN pip install --no-cache-dir --break-system-packages \
    ./tdv_profiler ./mcp/layer0'[all]' ./mcp/layer1'[all]' \
    && pip install --no-cache-dir --break-system-packages ./data_prep \
    && pip install --no-cache-dir --break-system-packages ./batch_runner

# Fix ownership
RUN chown -R agent:agent /opt/agent

# Make scripts executable
RUN chmod +x scripts/*.sh 2>/dev/null || true

# Ensure app/ is importable
ENV PYTHONPATH=/opt/agent

# Runtime environment defaults
ENV AGENT_NAME=signal-agent
ENV WORKSPACE_PATH=/workspace
ENV LOG_LEVEL=INFO

# Create workspace mount point and .claude directories
RUN mkdir -p /workspace/data /workspace/output /workspace/reports \
    /workspace/.claude/commands /workspace/.claude/skills /workspace/.claude/agents \
    && chown -R agent:agent /workspace

# Symlink workspace so paths resolve correctly
RUN ln -sf /workspace /opt/agent/workspace

# Health check
HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=15s \
    CMD curl -sf -H "Authorization: Bearer ${AGENT_API_TOKEN}" http://localhost:8080/status || exit 1

EXPOSE 8080

USER agent
CMD ["/bin/bash", "-c", "/opt/agent/scripts/register-skills.sh && exec uvicorn app.main:app --host 0.0.0.0 --port 8080"]
