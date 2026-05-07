"""Custom Prometheus metrics for the streaming layer.

These complement the default HTTP metrics emitted by
``prometheus-fastapi-instrumentator`` (request count, request duration
histogram, status codes — all labeled by route + method). The signals here
are *domain-specific*: they track things you couldn't infer from raw HTTP
logs alone.

Each metric is registered against the global :class:`prometheus_client`
registry on import; Prometheus scrapes them off the ``/metrics`` endpoint
mounted in :mod:`app.main`.
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

# Number of playback tokens minted, by scope. A spike here without a
# matching spike in segment requests means players are re-minting tokens
# but never actually streaming — usually a frontend bug.
playback_tokens_issued_total = Counter(
    "playback_tokens_issued_total",
    "Playback JWTs minted by /playback endpoints",
    ["scope"],
)

# Token verification failures. The ``reason`` label is the AppError code so
# you can build alerts like "ip_mismatch rate > 5/min".
playback_token_rejections_total = Counter(
    "playback_token_rejections_total",
    "Playback tokens rejected during verification",
    ["reason"],
)

# Each HLS segment fetch. Divide by ``HLS_SEGMENT_SECONDS`` per minute to
# approximate concurrent viewers.
hls_segment_requests_total = Counter(
    "hls_segment_requests_total",
    "HLS segment requests served",
    ["source"],  # "local" or "s3"
)

# Fires when ``open_range`` falls through to the S3 fallback path —
# i.e. the local cache was missing for a key. Should stay near zero once
# the bind-mounted media/ has been warmed.
s3_stream_fallback_total = Counter(
    "s3_stream_fallback_total",
    "Reads served from S3 because the local cache missed",
)

# HLS packaging outcomes from the BackgroundTask.
hls_packaging_total = Counter(
    "hls_packaging_total",
    "HLS packaging runs completed",
    ["outcome"],  # "ready" | "failed"
)
hls_packaging_duration_seconds = Histogram(
    "hls_packaging_duration_seconds",
    "Wall-clock seconds ffmpeg spent packaging a lesson video",
    buckets=(5, 15, 30, 60, 120, 300, 600, 1800),
)

# In-flight count of HLS packaging jobs — a Gauge so it can go down too.
# When this stays non-zero for long, ffmpeg can't keep up with uploads.
hls_packaging_in_flight = Gauge(
    "hls_packaging_in_flight",
    "Number of HLS packaging jobs currently running",
)
