from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

OUT = Path("output/pdf/mem-maker-gce-deployment-recommendation-2026-09-08.pdf")

styles = getSampleStyleSheet()
styles.add(ParagraphStyle(
    name="DocTitle", parent=styles["Title"], fontName="Helvetica-Bold",
    fontSize=24, leading=29, textColor=colors.HexColor("#12314d"),
    alignment=TA_CENTER, spaceAfter=9,
))
styles.add(ParagraphStyle(
    name="Subtitle", parent=styles["BodyText"], fontName="Helvetica",
    fontSize=10.5, leading=14, textColor=colors.HexColor("#506273"),
    alignment=TA_CENTER, spaceAfter=20,
))
styles.add(ParagraphStyle(
    name="H1Blue", parent=styles["Heading1"], fontName="Helvetica-Bold",
    fontSize=16, leading=20, textColor=colors.HexColor("#12314d"),
    spaceBefore=16, spaceAfter=8,
))
styles.add(ParagraphStyle(
    name="H2Blue", parent=styles["Heading2"], fontName="Helvetica-Bold",
    fontSize=12.5, leading=16, textColor=colors.HexColor("#1d5a7a"),
    spaceBefore=12, spaceAfter=6,
))
styles.add(ParagraphStyle(
    name="BodyClean", parent=styles["BodyText"], fontName="Helvetica",
    fontSize=9.4, leading=13.2, spaceAfter=6,
))
styles.add(ParagraphStyle(
    name="BulletClean", parent=styles["BodyText"], fontName="Helvetica",
    fontSize=9.4, leading=13.2, leftIndent=14, firstLineIndent=-9,
    spaceAfter=3,
))
styles.add(ParagraphStyle(
    name="Callout", parent=styles["BodyText"], fontName="Helvetica-Bold",
    fontSize=9.5, leading=13.4, textColor=colors.HexColor("#5c2e00"),
    backColor=colors.HexColor("#fff3d6"), borderColor=colors.HexColor("#e2a23a"),
    borderWidth=0.5, borderPadding=8, spaceBefore=7, spaceAfter=9,
))
styles.add(ParagraphStyle(
    name="Small", parent=styles["BodyText"], fontName="Helvetica",
    fontSize=8, leading=10.5, textColor=colors.HexColor("#4b5563"),
    spaceAfter=4,
))


def p(text: str, style: str = "BodyClean") -> Paragraph:
    return Paragraph(escape(text).replace("\n", "<br/>"), styles[style])


def h1(text: str) -> Paragraph:
    return p(text, "H1Blue")


def h2(text: str) -> Paragraph:
    return p(text, "H2Blue")


def bullet(text: str) -> Paragraph:
    return Paragraph("&bull; " + escape(text), styles["BulletClean"])


def code(text: str) -> Preformatted:
    return Preformatted(text.strip("\n"), ParagraphStyle(
        "Code", fontName="Courier", fontSize=7.2, leading=9.2,
        textColor=colors.HexColor("#17212b"), backColor=colors.HexColor("#f3f6f8"),
        borderColor=colors.HexColor("#c7d3db"), borderWidth=0.5,
        borderPadding=7, leftIndent=0, rightIndent=0, spaceBefore=4, spaceAfter=8,
    ), maxLineLength=96, newLineChars="  ")


def table(headers: list[str], rows: list[list[str]], widths: list[float]) -> Table:
    data = [[p(cell, "Small") for cell in headers]]
    data += [[p(cell, "Small") for cell in row] for row in rows]
    result = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
    result.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#12314d")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#b9c7d1")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f8fa")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return result


def header_footer(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(colors.HexColor("#d2dbe2"))
    canvas.line(doc.leftMargin, letter[1] - 0.48 * inch, letter[0] - doc.rightMargin, letter[1] - 0.48 * inch)
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#506273"))
    canvas.drawString(doc.leftMargin, letter[1] - 0.36 * inch, "Mem Maker - Google Cloud VM Deployment Recommendation")
    canvas.drawRightString(letter[0] - doc.rightMargin, 0.35 * inch, f"Page {doc.page}")
    canvas.restoreState()


story = []
story += [Spacer(1, 0.45 * inch), p("Mem Maker", "DocTitle"), p("Google Cloud VM Deployment Recommendation", "DocTitle"),
          p("Analysis and deployment-planning ticket - prepared September 8, 2026", "Subtitle")]
story += [p("Decision summary", "Callout"), p(
    "Use one on-demand e2-medium VM in us-central1 with a 30-GB pd-standard boot disk, an ephemeral external IPv4 address, and a source-IP-restricted firewall. Run it only for active testing, then stop it. Do not provision anything until King Trizzen explicitly approves this recommendation."
)]
story += [h1("1. Recommendation and scope")]
story += [p("This document packages the full deployment recommendation. It is analysis only: no Google Cloud resources, firewall rules, VM, database migration, production change, or repository change was made."),
          p("The first deployment is a restricted HTTP test environment, not a production public service. It reuses the existing Docker Compose architecture and does not redesign Mem Maker.")]
story += [h2("Recommended shape")]
story += [table(["Component", "Recommendation", "Reason"], [
    ["Region / zone", "us-central1 / us-central1-a", "Low US pricing and Free Tier-eligible region."],
    ["Compute", "e2-medium, on-demand", "Minimum sensible RAM and CPU for this five-container development stack."],
    ["Disk", "30-GB pd-standard boot disk", "Enough for OS, images, named volumes, source, and limited build cache at minimal cost."],
    ["Public address", "Ephemeral IPv4", "Released when stopped; no static address left billing between test sessions."],
    ["Network tier", "Standard Tier", "Appropriate for a restricted test system and lower egress exposure."],
    ["Access", "OS Login plus trusted CIDR only", "No public-wide SSH or application endpoints."],
], [1.15*inch, 1.8*inch, 3.65*inch])]
story += [h1("2. Existing Mem Maker Docker architecture")]
story += [p("The current Compose contract has five services. Browser authentication uses Keycloak Authorization Code + PKCE; FastAPI validates the Keycloak issuer and audience; MariaDB stores application data; Keycloak uses PostgreSQL."),
          table(["Service", "Role", "State that persists"], [
              ["frontend", "Next.js development server on port 3000", "Source bind mount and frontend-node-modules named volume."],
              ["backend", "FastAPI/Uvicorn on port 8000", "Source bind mount; transient analysis state in container /tmp."],
              ["app-db", "MariaDB 11.4 on host port 3307", "app-db-data named volume."],
              ["keycloak", "Keycloak 26.6.3 on port 8080", "Identity state is stored in Keycloak PostgreSQL."],
              ["keycloak-db", "PostgreSQL 16 for Keycloak", "keycloak-db-data named volume."],
          ], [1.05*inch, 2.15*inch, 3.4*inch])]
story += [p("The local Compose file exposes ports 3000, 8000, 8080, and 3307, uses Next.js development mode and Uvicorn --reload, enables a development-auth path, and sets OIDC, CORS, and Keycloak redirect URLs to localhost. Opening firewall ports without configuration overrides would not create a safe working public test deployment.")]
story += [h2("Observed local resource usage")]
story += [table(["Component", "Observed memory"], [
    ["Keycloak", "~560 MiB"], ["Next.js frontend", "~495 MiB"], ["MariaDB", "~188 MiB"],
    ["FastAPI backend", "~121 MiB"], ["Keycloak PostgreSQL", "~55 MiB"], ["Container subtotal", "~1.42 GiB"],
], [3.0*inch, 3.6*inch])]
story += [p("The subtotal excludes the guest OS, Docker daemon, filesystem cache, and build spikes. The current images occupy roughly 5.8 GB before Docker cache, named volumes, the OS, or future rebuilds.")]
story += [h1("3. VM sizing decision")]
story += [table(["Option", "Resources", "Assessment"], [
    ["e2-micro", "0.25 shared vCPU, 1 GB RAM", "Reject. It is Free Tier eligible but cannot sensibly run the observed workload."],
    ["e2-small", "0.5 shared vCPU, 2 GB RAM", "Not recommended. Too likely to swap or OOM during Keycloak/Next.js activity and image builds."],
    ["e2-medium", "1 shared vCPU, 4 GB RAM", "Recommended minimum. Adequate runtime headroom at the lowest practical cost."],
    ["e2-standard-2", "2 vCPU, 8 GB RAM", "Fallback only if testing demonstrates build-time memory pressure or unacceptable performance."],
], [1.2*inch, 1.7*inch, 3.7*inch])]
story += [p("Google documents e2-medium as a 4-GB shared-core VM with one fractional vCPU of sustained capacity. The e2-micro and e2-small provide only 1 GB and 2 GB. The e2-micro Free Tier does not make e2-medium compute free.")]
story += [h1("4. Cost model")]
story += [p("Assumptions: Linux, on-demand pricing, 730 hours/month, us-central1, no load balancer, no Cloud SQL, no Cloud NAT, no Artifact Registry, no scheduled snapshot policy, no Ops Agent, and light interactive testing from North America. Re-run the Google Cloud Pricing Calculator against the actual billing account before approval because rates, taxes, and account-wide free allocations can change.")]
story += [h2("Continuously running - estimated monthly baseline")]
story += [table(["Component", "Assumption", "Estimate/month"], [
    ["e2-medium compute", "730 hr x about $0.0335/hr", "$24.46"],
    ["30-GB pd-standard", "30 GB x about $0.04/GB-month", "$1.20"],
    ["Ephemeral public IPv4", "730 hr x $0.005/hr while attached/running", "$3.65"],
    ["Standard-Tier egress", "Light testing within account free allowance", "$0.00 expected"],
    ["Snapshots", "None initially", "$0.00"],
    ["Cloud Logging", "No agent / no verbose firewall logging initially", "$0.00 expected"],
    ["Expected baseline", "Excludes tax and excess egress", "~$29.31"],
], [1.5*inch, 3.35*inch, 1.35*inch])]
story += [h2("Intentionally stopped - cost behavior")]
story += [table(["Resource", "Does it survive stop?", "Billing while stopped?"], [
    ["e2-medium CPU/RAM", "VM configuration remains", "No compute charge."],
    ["Ephemeral external IPv4", "Released; next start gets a new address", "No."],
    ["30-GB boot disk", "Yes", "Yes: about $1.20/month unless unused Free Tier disk allocation covers it."],
    ["Docker images, source, .env, volumes", "Yes; all live on boot disk", "Included in boot-disk cost."],
    ["Standard snapshots", "Yes", "Yes: actual compressed snapshot data is billed."],
    ["Static IPv4, if created", "Yes", "Yes. Avoid it for this first deployment."],
    ["Cloud Logging data", "Depends on configuration", "Possibly."],
], [1.55*inch, 2.45*inch, 2.2*inch])]
story += [p("At about 40 running hours/month, estimated compute is ~$1.34 and external IPv4 is ~$0.20; including the boot disk, the expected total is about $2.74/month before snapshots, excess egress, or logging. A stopped e2-medium has no compute charge, but stopping it does not make the persistent disk free.")]
story += [p("A 30-GB standard disk may be covered by unused Compute Engine Free Tier disk allocation. Treat this as a possible credit, not a promise: it is account-wide and may already be used."),
          p("Regional standard snapshots are incremental and billed for stored data, approximately $0.05/GiB-month in us-central1. Do not schedule snapshots initially. If a recovery point is needed, stop containers cleanly, make one manual snapshot, and delete it deliberately when no longer needed.")]
story += [h1("5. Security prerequisite")]
story += [p("Before any public deployment, rotate/revoke the provider credential that is currently present in tracked source defaults and environment example material. This document intentionally does not reproduce the credential."),
          bullet("Remove the credential from tracked source and defaults; require an untracked VM-local .env or later secret-management mechanism."),
          bullet("For the first test deployment, set OPENAI_API_KEY= empty. The application documents a deterministic/manual-safe fallback rather than a paid provider request."),
          bullet("Do not use seeded local Keycloak users or local Keycloak administrator credentials outside local development."),
          bullet("Do not place secrets in Git, VM metadata, Dockerfiles, gcloud command lines, or shell history.")]
story += [h1("6. Proposed test architecture")]
story += [code("King Trizzen's fixed public IP/CIDR\n        |\n        | TCP 22, 3000, 8000, 8080 only\n        v\nGCE VPC firewall: explicit allow, then explicit deny for every other source\n        |\n        v\nOne e2-medium VM (Ubuntu 24.04, us-central1)\n  |- frontend :3000  public test UI\n  |- backend  :8000  public test API, trusted source only\n  |- Keycloak :8080  public OIDC endpoint, trusted source only\n  |- MariaDB  :3307  never allowed through firewall\n  `- Keycloak PostgreSQL  no host port")]
story += [p("The first test URL is http://EPHEMERAL_VM_IP:3000. It is HTTP-only, source-IP restricted, and not intended for broad public use. This intentionally avoids a load balancer, Cloud SQL migration, static IP, DNS, reverse proxy, and certificate management.")]
story += [h1("7. Provisioning procedure - execute only after approval")]
story += [p("Use a dedicated project such as mem-maker-test. Replace placeholders before execution.")]
story += [code("PROJECT_ID=\"mem-maker-test\"\nZONE=\"us-central1-a\"\nNETWORK=\"default\"\nVM_NAME=\"mem-maker-test\"\nTRUSTED_CIDR=\"YOUR_CURRENT_PUBLIC_IP/32\"")]
story += [h2("7.1 Enable Compute Engine and create restrictive firewalls first")]
story += [p("Create the allow rule before the deny rule. The rules deliberately limit SSH, frontend, API, and Keycloak to the trusted CIDR and prevent the default VPC rules from leaving the services or MariaDB accessible to other sources.")]
story += [code("gcloud services enable compute.googleapis.com --project=\"${PROJECT_ID}\"\n\ngcloud compute firewall-rules create mem-maker-test-allow-trusted \\\n+  --project=\"${PROJECT_ID}\" --network=\"${NETWORK}\" \\\n+  --direction=INGRESS --priority=900 --action=ALLOW \\\n+  --target-tags=mem-maker-test --source-ranges=\"${TRUSTED_CIDR}\" \\\n+  --rules=tcp:22,tcp:3000,tcp:8000,tcp:8080\n\ngcloud compute firewall-rules create mem-maker-test-deny-other-ingress \\\n+  --project=\"${PROJECT_ID}\" --network=\"${NETWORK}\" \\\n+  --direction=INGRESS --priority=1000 --action=DENY \\\n+  --target-tags=mem-maker-test --source-ranges=0.0.0.0/0 \\\n+  --rules=tcp:22,tcp:3000,tcp:8000,tcp:8080,tcp:3307")]
story += [p("Do not enable firewall-rule logging initially unless troubleshooting requires it; it produces Cloud Logging ingestion. Do not open port 3307. Do not substitute 0.0.0.0/0 for the trusted CIDR.")]
story += [h2("7.2 Create the VM")]
story += [code("gcloud compute instances create \"${VM_NAME}\" \\\n+  --project=\"${PROJECT_ID}\" --zone=\"${ZONE}\" \\\n+  --machine-type=e2-medium \\\n+  --image-family=ubuntu-2404-lts-amd64 --image-project=ubuntu-os-cloud \\\n+  --boot-disk-size=30GB --boot-disk-type=pd-standard \\\n+  --network=\"${NETWORK}\" --network-tier=STANDARD --address='' \\\n+  --tags=mem-maker-test --metadata=enable-oslogin=TRUE \\\n+  --shielded-secure-boot --shielded-vtpm --shielded-integrity-monitoring \\\n+  --no-service-account --no-scopes\n\ngcloud compute instances describe \"${VM_NAME}\" \\\n+  --project=\"${PROJECT_ID}\" --zone=\"${ZONE}\" \\\n+  --format='get(status,networkInterfaces[0].accessConfigs[0].natIP)'")]
story += [p("The VM has an ephemeral address rather than a static address. Record the shown IP for the active test session only. It will change when the VM is stopped and started.")]
story += [h2("7.3 Bootstrap Docker")]
story += [code("gcloud compute ssh \"${VM_NAME}\" --project=\"${PROJECT_ID}\" --zone=\"${ZONE}\"\n\nsudo apt-get update\nsudo apt-get install -y ca-certificates curl git\nsudo install -m 0755 -d /etc/apt/keyrings\nsudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc\nsudo chmod a+r /etc/apt/keyrings/docker.asc\necho \"deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo \"${VERSION_CODENAME}\") stable\" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null\nsudo apt-get update\nsudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin\nsudo systemctl enable --now docker\nsudo usermod -aG docker \"${USER}\"\nsudo fallocate -l 2G /swapfile\nsudo chmod 600 /swapfile\nsudo mkswap /swapfile\nsudo swapon /swapfile\necho '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab\nexit")]
story += [p("Reconnect after exit so Docker group membership takes effect. The 2-GB swap file has no separate GCP resource charge; it uses a small part of the boot disk and is only a safety cushion.")]
story += [h2("7.4 Transfer a reviewed source revision without transferring secrets")]
story += [p("Prefer a source archive from an approved commit instead of copying a working directory. This avoids shipping .env, local virtual environments, test artifacts, uncommitted work, or GitHub credentials to the VM.")]
story += [code("COMMIT_SHA=\"$(git -C /Users/triz/paladin/mem_master rev-parse HEAD)\"\ngit -C /Users/triz/paladin/mem_master archive --format=tar \"${COMMIT_SHA}\" | gzip > \"/tmp/mem-master-${COMMIT_SHA}.tar.gz\ngcloud compute scp \"/tmp/mem-master-${COMMIT_SHA}.tar.gz\" \"${VM_NAME}:/tmp/mem-master-${COMMIT_SHA}.tar.gz\" --project=\"${PROJECT_ID}\" --zone=\"${ZONE}\"\n\n# On the VM\nsudo install -d -o \"${USER}\" -g \"${USER}\" /srv/mem-master\ntar -xzf \"/tmp/mem-master-${COMMIT_SHA}.tar.gz\" -C /srv/mem-master\nrm \"/tmp/mem-master-${COMMIT_SHA}.tar.gz\"\ncd /srv/mem-master")]
story += [h2("7.5 Create the VM-local .env")]
story += [code("cd /srv/mem-master\numask 077\ntouch .env\nchmod 600 .env\n\n# Populate .env through a terminal editor or secure paste:\nDB_NAME=mem_master\nDB_USER=mem\nDB_PASSWORD=GENERATE_A_NEW_RANDOM_VALUE\nDB_ROOT_PASSWORD=GENERATE_A_NEW_RANDOM_VALUE\nKEYCLOAK_DB_NAME=keycloak\nKEYCLOAK_DB_USER=keycloak\nKEYCLOAK_DB_PASSWORD=GENERATE_A_NEW_RANDOM_VALUE\nKEYCLOAK_ADMIN=CHOOSE_A_NONDEFAULT_ADMIN_NAME\nKEYCLOAK_ADMIN_PASSWORD=GENERATE_A_NEW_RANDOM_VALUE\nOPENAI_API_KEY=\nOPENAI_MODEL=gpt-5.6-terra\nPUBLIC_APP_URL=http://EPHEMERAL_VM_IP:3000\nPUBLIC_API_URL=http://EPHEMERAL_VM_IP:8000/api/v1\nPUBLIC_KEYCLOAK_URL=http://EPHEMERAL_VM_IP:8080")]
story += [h2("7.6 Create a VM-only Compose override and Keycloak realm copy")]
story += [code("# /srv/mem-master/docker-compose.gce.yml\nservices:\n  keycloak:\n    environment:\n      KC_HOSTNAME: ${PUBLIC_KEYCLOAK_URL}\n    volumes:\n      - ./docker/keycloak-gce:/opt/keycloak/data/import:ro\n  backend:\n    environment:\n      APP_ENV: testing\n      DEV_AUTH_ENABLED: \"false\"\n      KEYCLOAK_PUBLIC_ISSUER: ${PUBLIC_KEYCLOAK_URL}/realms/mem-master\n      CORS_ORIGINS: '[\"${PUBLIC_APP_URL}\"]'\n  frontend:\n    environment:\n      NEXT_PUBLIC_API_BASE_URL: ${PUBLIC_API_URL}\n      NEXT_PUBLIC_KEYCLOAK_URL: ${PUBLIC_KEYCLOAK_URL}\n      NEXT_PUBLIC_KEYCLOAK_REALM: mem-master\n      NEXT_PUBLIC_KEYCLOAK_CLIENT_ID: mem-master-frontend\n\nmkdir -p /srv/mem-master/docker/keycloak-gce\ncp /srv/mem-master/docker/keycloak/mem-master-realm.json /srv/mem-master/docker/keycloak-gce/mem-master-realm.json")]
story += [bullet("In the copied realm only, replace localhost/127.0.0.1 redirect URIs, web origins, and post-logout URI with http://EPHEMERAL_VM_IP:3000."),
          bullet("Change the display name to identify the test environment and remove seeded local users."),
          bullet("After first startup, use the source-restricted Keycloak Admin Console at http://EPHEMERAL_VM_IP:8080/admin to create one unique test user with a strong password."),
          p("Realm import happens only on the first initialization of the Keycloak PostgreSQL volume. After first start, change redirect URIs and origins in the restricted Admin Console; editing the JSON copy will not change an already-imported realm. Do not run scripts/reset-local.sh on the VM because it destroys named volumes.")]
story += [h2("7.7 Start and verify")]
story += [code("cd /srv/mem-master\ndocker compose --env-file .env -f docker-compose.yml -f docker-compose.gce.yml up --build -d\ndocker compose --env-file .env -f docker-compose.yml -f docker-compose.gce.yml ps\ncurl --fail --silent http://127.0.0.1:8000/api/v1/health\ncurl --fail --silent --output /dev/null http://127.0.0.1:3000/")]
story += [bullet("From the trusted CIDR only, open http://EPHEMERAL_VM_IP:3000."), bullet("Verify Keycloak login/logout, one authenticated API action, the API health endpoint, and that MariaDB is not publicly reachable.")]
story += [h1("8. Normal pause, restart, and cost verification")]
story += [h2("Stop the containers, preserving data")]
story += [code("cd /srv/mem-master\ndocker compose --env-file .env -f docker-compose.yml -f docker-compose.gce.yml stop\ndocker compose --env-file .env -f docker-compose.yml -f docker-compose.gce.yml ps")]
story += [p("Use stop for normal pauses. docker compose down preserves named volumes by default but removes containers and transient state. Never add -v unless intentional destruction of MariaDB and Keycloak data is approved.")]
story += [h2("Stop the VM")]
story += [code("gcloud compute instances stop \"${VM_NAME}\" --project=\"${PROJECT_ID}\" --zone=\"${ZONE}\"")]
story += [p("Expected result: CPU/RAM billing stops; the ephemeral IPv4 releases; the boot disk, Docker images, source, .env, databases, and Docker volumes remain; the next start gets a new external IP and needs endpoint and Keycloak client-origin updates.")]
story += [h2("Start later")]
story += [code("gcloud compute instances start \"${VM_NAME}\" --project=\"${PROJECT_ID}\" --zone=\"${ZONE}\"\ngcloud compute instances describe \"${VM_NAME}\" --project=\"${PROJECT_ID}\" --zone=\"${ZONE}\" --format='get(networkInterfaces[0].accessConfigs[0].natIP)'\n\n# Update PUBLIC_APP_URL, PUBLIC_API_URL, and PUBLIC_KEYCLOAK_URL in .env,\n# then update Keycloak redirect URI/web origin in the restricted Admin Console.\ncd /srv/mem-master\ndocker compose --env-file .env -f docker-compose.yml -f docker-compose.gce.yml up -d --force-recreate keycloak backend frontend\ndocker compose --env-file .env -f docker-compose.yml -f docker-compose.gce.yml ps")]
story += [h2("Inspect remaining billable resources")]
story += [code("gcloud compute instances list --project=\"${PROJECT_ID}\"\ngcloud compute disks list --project=\"${PROJECT_ID}\"\ngcloud compute addresses list --project=\"${PROJECT_ID}\"\ngcloud compute snapshots list --project=\"${PROJECT_ID}\"\ngcloud compute firewall-rules list --project=\"${PROJECT_ID}\" --filter='name~mem-maker-test'")]
story += [p("When stopped, the recommended setup should show one stopped VM and one persistent disk. It should not show a retained external address. Investigate any retained address or snapshot before assuming idle cost is limited to the boot disk.")]
story += [h1("9. Billing safeguards")]
story += [bullet("Use a dedicated project linked to the intended billing account."),
          bullet("Create a $5/month project-scoped total-cost budget with actual and forecast thresholds at 50%, 90%, and 100%."),
          bullet("Create a second $35/month project-scoped budget with actual and forecast thresholds at 80%, 90%, and 100%."),
          bullet("Add a Cloud Monitoring email notification channel for King Trizzen and enable billing anomaly detection if available."),
          bullet("Do not install the Ops Agent or enable verbose firewall logging initially. If logging is later needed, set exclusions and retention deliberately."),
          bullet("Do not create a static IP, load balancer, Cloud NAT, Cloud SQL, managed DNS zone, Artifact Registry retention policy, or scheduled snapshot policy for the first test."),
          p("Cloud Billing budgets are alerts, not hard spending caps. Google documents that alerts-only budgets do not automatically stop use or billing. Programmatic Pub/Sub action can be considered later but is unnecessary for this first controlled test.")]
story += [h1("10. Risks, limitations, and future HTTPS path")]
story += [bullet("This is a restricted test deployment, not a production internet service. The existing stack uses start-dev, --reload, and Next development mode."),
          bullet("The raw public IP changes on every stop/start cycle. That operational step deliberately avoids a static-IP carrying cost."),
          bullet("A persistent disk protects VM stop/restart, not against disk deletion, data corruption, application errors, or project loss."),
          bullet("Finalized application data in MariaDB persists; backend temporary script-import analysis state is not a named volume and is transient."),
          bullet("If broader public access becomes necessary, pause rather than widen 3000/8000/8080 to the whole internet.")]
story += [p("Later, low-cost HTTPS can use one domain, a reserved static IPv4 only when stability is worth its continuing charge, and one Caddy or Nginx reverse-proxy container. Expose only 80/443; keep frontend, API, Keycloak, and databases behind it; use app/api/auth subdomains and free Let's Encrypt certificates. This avoids a managed HTTPS load balancer for a small VM but remains outside the first deployment.")]
story += [h1("11. Smallest next implementation ticket")]
story += [p("MEM-DEPLOY-01 - Safe ephemeral GCE test deployment for Mem Maker", "Callout")]
story += [bullet("Revoke/rotate the exposed provider credential, remove it from tracked defaults, and require a blank or VM-local provider key."),
          bullet("Add one reviewed deployment-only Compose overlay and deployment-only Keycloak-realm template without changing the local-development contract."),
          bullet("Provision exactly one us-central1 e2-medium VM with a 30-GB pd-standard disk, Standard Tier ephemeral IPv4, OS Login, no VM service account, and the restricted firewall above."),
          bullet("Deploy one approved Git commit via source archive, create new VM-local database and Keycloak credentials, start the existing Compose stack, and verify login plus API health from the approved CIDR."),
          bullet("Create both billing budgets before the VM starts. Stop containers and VM after acceptance; record remaining disk, snapshot, and address resources and expected idle cost.")]
story += [h2("Explicit non-goals")]
story += [bullet("No managed-database migration, public 0.0.0.0/0 exposure, static IP, domain, TLS, load balancer, Cloud Run rewrite, Cloud SQL migration, automated snapshot schedule, or production cutover."),
          bullet("No secret is committed to Git or placed in VM metadata.")]
story += [h1("12. Source references")]
story += [p("Repository evidence inspected: docker-compose.yml; README.md; docs/architecture.md; docker/keycloak/mem-master-realm.json; backend/app/auth.py; frontend/lib/auth.tsx; frontend/lib/api.ts."),
          p("Google Cloud sources consulted: Free Cloud features and trial offer; Compute Engine general-purpose machine documentation; Persistent Disk and snapshot pricing; VPC pricing; VM stop/start billing behavior; OS Login; VPC firewall rules; Cloud Billing budgets; Google Cloud Pricing Calculator."),
          p("This packaged document preserves the analysis conclusions and procedure from the original deployment recommendation. Prices are planning estimates, not a quote. Revalidate in the Pricing Calculator before approval.", "Small")]

OUT.parent.mkdir(parents=True, exist_ok=True)
doc = SimpleDocTemplate(
    str(OUT), pagesize=letter, rightMargin=0.62*inch, leftMargin=0.62*inch,
    topMargin=0.68*inch, bottomMargin=0.55*inch, title="Mem Maker GCE Deployment Recommendation",
    author="Codex",
)
doc.build(story, onFirstPage=header_footer, onLaterPages=header_footer)
print(OUT)
