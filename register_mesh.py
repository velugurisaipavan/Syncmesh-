"""Configure a three-node local Compose mesh; no sensor observations are generated."""
import os
import httpx


def main():
    token = os.environ["SYNCMESH_TOKEN"]
    with httpx.Client(timeout=20, headers={"Authorization": f"Bearer {token}"}, follow_redirects=False, trust_env=False) as client:
        for source in range(1, 4):
            for target in range(1, 4):
                if source == target:
                    continue
                response = client.put(f"http://localhost:{8080+source}/meta/nodes", json=dict(
                    url=f"http://node{target}:8080", latitude=42+(target-1)*.01, longitude=23., subscribed=False))
                response.raise_for_status()
    print("Peers registered. Replication subscriptions remain disabled until you explicitly enable them.")


if __name__ == "__main__":
    main()
