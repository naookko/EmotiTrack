# syntax=docker/dockerfile:1

FROM mongo:7.0

# Persist database files outside the container by default
VOLUME ["/data/db"]

# Expose the default MongoDB port so the API can reach it via localhost:27017
EXPOSE 27017

# Basic health check keeps the container marked healthy once Mongo is ready
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["mongosh", "--quiet", "--eval", "db.adminCommand('ping')"]
