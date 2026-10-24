#!/bin/sh
set -eu
until mongosh --quiet --host "$MONGO_HOST" --eval 'db.adminCommand({ping:1}).ok' >/dev/null 2>&1; do sleep 2; done
mongosh --quiet --host "$MONGO_HOST" --eval "try { rs.status() } catch (e) { rs.initiate({_id: '$REPLICA_SET', members: [{_id: 0, host: '$MONGO_HOST:27017'}]}) }"
until mongosh --quiet --host "$MONGO_HOST" --eval 'if(!db.hello().isWritablePrimary) quit(1)' >/dev/null 2>&1; do sleep 2; done
