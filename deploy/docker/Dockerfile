FROM 1password/op:2 AS onepassword_cli

FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MCP_HOST=0.0.0.0 \
    MCP_PORT=8765 \
    EDGARS_MCP_RUNTIME_DIR=/var/lib/edgars-mcp

RUN useradd --create-home --uid 1000 edgar
WORKDIR /app
COPY --from=onepassword_cli /usr/local/bin/op /usr/local/bin/op
COPY pyproject.toml README.md ./
COPY src ./src
COPY deploy/docker/start.sh /usr/local/bin/edgars-mcp-container-start
COPY deploy/docker/check.sh /usr/local/bin/edgars-mcp-container-check
RUN python -m pip install --no-cache-dir .

RUN mkdir -p /var/lib/edgars-mcp/run /var/lib/edgars-mcp/state /var/lib/edgars-mcp/logs /var/lib/edgars-mcp/cache /var/lib/edgars-mcp/tmp \
    && chmod 0755 /usr/local/bin/edgars-mcp-container-start /usr/local/bin/edgars-mcp-container-check \
    && chown -R edgar:edgar /var/lib/edgars-mcp

USER edgar
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/health', timeout=3)" || exit 1

CMD ["/usr/local/bin/edgars-mcp-container-start"]
