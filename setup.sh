#!/bin/bash
# ============================================================
# WheellsVerse Bot Ecosystem — macOS Setup Script
# Run: bash setup.sh
# ============================================================

set -e  # Exit on any error

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
WHITE='\033[1;37m'
NC='\033[0m' # No Color

BOLD='\033[1m'

print_banner() {
echo -e "${CYAN}"
echo "  ██╗    ██╗██╗  ██╗███████╗███████╗██╗     ██╗     ███████╗"
echo "  ██║    ██║██║  ██║██╔════╝██╔════╝██║     ██║     ██╔════╝"
echo "  ██║ █╗ ██║███████║█████╗  █████╗  ██║     ██║     ███████╗"
echo "  ██║███╗██║██╔══██║██╔══╝  ██╔══╝  ██║     ██║     ╚════██║"
echo "  ╚███╔███╔╝██║  ██║███████╗███████╗███████╗███████╗███████║"
echo "   ╚══╝╚══╝ ╚═╝  ╚═╝╚══════╝╚══════╝╚══════╝╚══════╝╚══════╝"
echo -e "${WHITE}         Bot Ecosystem — Setup Script${NC}"
echo ""
}

step() { echo -e "\n${CYAN}[STEP]${NC} ${BOLD}$1${NC}"; }
ok()   { echo -e "${GREEN}[✓]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
err()  { echo -e "${RED}[✗]${NC} $1"; exit 1; }

print_banner

# ─── 1. Check OS ──────────────────────────────────────────────────────────────
step "Checking environment"
if [[ "$OSTYPE" != "darwin"* ]]; then
    warn "Not macOS — script optimized for Mac. Some features may differ on Linux."
fi
ok "OS: $(uname -s) $(uname -r)"

# ─── 2. Check Python ──────────────────────────────────────────────────────────
step "Checking Python"
if ! command -v python3 &>/dev/null; then
    err "Python 3 not found. Install from: https://www.python.org/downloads/"
fi
PYTHON_VER=$(python3 --version 2>&1)
ok "Found: $PYTHON_VER"

# Require Python 3.10+
PYTHON_MINOR=$(python3 -c "import sys; print(sys.version_info.minor)")
if [[ $PYTHON_MINOR -lt 10 ]]; then
    warn "Python 3.10+ recommended. You have Python 3.$PYTHON_MINOR"
    warn "Update at: https://www.python.org/downloads/"
fi

# ─── 3. Check/Create virtual environment ─────────────────────────────────────
step "Setting up virtual environment"
VENV_DIR="./venv"
if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
    ok "Virtual environment created"
else
    ok "Virtual environment exists"
fi

source "$VENV_DIR/bin/activate"
ok "Virtual environment activated"

# ─── 4. Upgrade pip ───────────────────────────────────────────────────────────
step "Upgrading pip"
pip install --upgrade pip --quiet
ok "pip upgraded"

# ─── 5. Install requirements ──────────────────────────────────────────────────
step "Installing Python packages"
echo "This may take 2-3 minutes..."
pip install -r requirements.txt --quiet
ok "All packages installed"

# ─── 6. Create .env if missing ────────────────────────────────────────────────
step "Setting up .env"
if [ ! -f ".env" ]; then
    cp .env.example .env
    warn ".env created from .env.example — EDIT IT with your API keys before running bots!"
    warn "  → Open: nano .env  OR  code .env  OR  open .env"
else
    ok ".env file exists"
fi

# ─── 7. Create directory structure ────────────────────────────────────────────
step "Creating directory structure"
mkdir -p logs outputs data configs

# Category output dirs
for cat in marketing business customer_support sales social_media writing assistant problem_solving time_management ecommerce specialized; do
    mkdir -p "outputs/$cat"
done

ok "Directories created"

# ─── 8. Create all bot config.json files (if missing) ─────────────────────────
step "Initializing bot configs"
python3 - << 'PYEOF'
import os
import json
from pathlib import Path

configs = {
    # Marketing
    "bots/marketing/11_ab_testing":         {"description": "A/B test variants for emails, ads, landing pages", "enabled": True, "schedule": "@weekly tue 09:00"},
    "bots/marketing/12_brand_voice":         {"description": "Brand voice guide and content style system", "enabled": True, "schedule": "@monthly"},
    "bots/marketing/13_trend_analyzer":     {"description": "Market and content trend analysis", "enabled": True, "schedule": "@weekly mon 07:00"},
    "bots/marketing/14_hashtag_generator":  {"description": "Hashtag strategy for social platforms", "enabled": True, "schedule": "@daily 08:30"},
    "bots/marketing/15_outreach_automation": {"description": "Cold outreach templates and sequences", "enabled": True, "schedule": "@weekly wed 09:00"},
    "bots/marketing/16_blog_publisher":     {"description": "Publish-ready SEO blog posts", "enabled": True, "schedule": "@daily 08:00", "topic": "AI automation trends"},
    "bots/marketing/17_newsletter_generator": {"description": "Weekly newsletter content", "enabled": True, "schedule": "@weekly fri 08:00"},
    "bots/marketing/18_conversion_optimizer": {"description": "CRO audit and recommendations", "enabled": True, "schedule": "@weekly thu 09:00"},
    "bots/marketing/19_marketing_strategy":  {"description": "Full marketing strategy generator", "enabled": True, "schedule": "@monthly"},
    "bots/marketing/20_growth_hacking":      {"description": "Growth hacking tactics and experiments", "enabled": True, "schedule": "@weekly mon 09:00"},
    # Business
    "bots/business/21_business_plan":       {"description": "Investor-ready business plan", "enabled": True, "schedule": "@monthly", "business_name": "WheellsVerse"},
    "bots/business/22_financial_projection": {"description": "36-month financial projections", "enabled": True, "schedule": "@monthly"},
    "bots/business/23_kpi_tracker":         {"description": "Track and analyze business KPIs", "enabled": True, "schedule": "@weekly mon 08:00"},
    "bots/business/24_expense_tracker":     {"description": "Business expense analysis and reporting", "enabled": True, "schedule": "@monthly"},
    "bots/business/25_workflow_automation": {"description": "Business process automation design", "enabled": True, "schedule": "@weekly"},
    "bots/business/26_hiring_assistant":    {"description": "Job descriptions and interview questions", "enabled": True, "schedule": "@weekly"},
    "bots/business/27_legal_document":      {"description": "Basic legal document templates", "enabled": True, "schedule": "@monthly"},
    "bots/business/28_operations_optimizer": {"description": "Operations efficiency analysis", "enabled": True, "schedule": "@monthly"},
    # Customer Support
    "bots/customer_support/29_auto_reply_email": {"description": "AI-powered customer email replies", "enabled": True, "schedule": "@every_hour"},
    "bots/customer_support/30_faq_chatbot": {"description": "Local FAQ chatbot", "enabled": True, "schedule": "@every_hour"},
    "bots/customer_support/31_ticket_classifier": {"description": "Classify and triage support tickets", "enabled": True, "schedule": "@every_30min"},
    # Sales
    "bots/sales/32_cold_email":             {"description": "Cold email sequences", "enabled": True, "schedule": "@daily 09:00"},
    "bots/sales/33_follow_up":              {"description": "Sales follow-up automation", "enabled": True, "schedule": "@daily 10:00"},
    "bots/sales/34_crm_updater":            {"description": "CRM data and contact updates", "enabled": True, "schedule": "@daily 08:00"},
    "bots/sales/35_proposal_generator":     {"description": "Professional sales proposals", "enabled": True, "schedule": "@weekly"},
    "bots/sales/36_negotiation_assistant":  {"description": "Negotiation strategy and scripts", "enabled": True, "schedule": "@weekly"},
    # Social Media
    "bots/social_media/37_auto_post":       {"description": "7-day social media post calendar", "enabled": True, "schedule": "@weekly sun 20:00"},
    "bots/social_media/38_content_scheduler": {"description": "Content scheduling plan", "enabled": True, "schedule": "@weekly mon 07:00"},
    "bots/social_media/39_engagement_reply": {"description": "Comment and DM engagement replies", "enabled": True, "schedule": "@every_6hours"},
    "bots/social_media/40_dm_automation":   {"description": "DM outreach and response templates", "enabled": True, "schedule": "@daily 09:00"},
    "bots/social_media/41_viral_analyzer":  {"description": "Viral content analysis and replication", "enabled": True, "schedule": "@daily 07:00"},
    "bots/social_media/42_caption_generator": {"description": "Social media captions", "enabled": True, "schedule": "@daily 08:00"},
    "bots/social_media/43_video_script":    {"description": "Short-form video scripts", "enabled": True, "schedule": "@weekly tue 09:00"},
    "bots/social_media/44_trend_scraper":   {"description": "Social media trend research", "enabled": True, "schedule": "@daily 06:00"},
    "bots/social_media/45_multi_platform_poster": {"description": "Cross-platform content adaptation", "enabled": True, "schedule": "@daily 08:30"},
    # Writing
    "bots/writing/46_blog_writer":          {"description": "Full blog articles", "enabled": True, "schedule": "@daily 08:00"},
    "bots/writing/47_book_writer":          {"description": "Book chapters and outlines", "enabled": True, "schedule": "@weekly"},
    "bots/writing/48_script_writer":        {"description": "Video and podcast scripts", "enabled": True, "schedule": "@weekly"},
    "bots/writing/49_resume_generator":     {"description": "ATS-optimized resumes", "enabled": True, "schedule": "@monthly"},
    "bots/writing/50_cover_letter":         {"description": "Personalized cover letters", "enabled": True, "schedule": "@monthly"},
    "bots/writing/51_copywriter":           {"description": "Sales and marketing copy", "enabled": True, "schedule": "@daily"},
    "bots/writing/52_technical_writer":     {"description": "Technical documentation", "enabled": True, "schedule": "@weekly"},
    "bots/writing/53_proofreader":          {"description": "Grammar and style editing", "enabled": True, "schedule": "@daily"},
    # Assistant
    "bots/assistant/54_task_assistant":     {"description": "Daily task planning and prioritization", "enabled": True, "schedule": "@daily 07:00"},
    "bots/assistant/55_reminder_bot":       {"description": "Smart reminder system", "enabled": True, "schedule": "@every_30min"},
    "bots/assistant/56_file_organizer":     {"description": "Organize files by type and date", "enabled": True, "schedule": "@daily 23:00"},
    # Problem Solving
    "bots/problem_solving/57_debugging_assistant": {"description": "Code debugging and analysis", "enabled": True, "schedule": "@every_2hours"},
    "bots/problem_solving/58_research_bot": {"description": "Deep research reports", "enabled": True, "schedule": "@daily 09:00"},
    # Time Management
    "bots/time_management/59_schedule_optimizer": {"description": "Daily schedule optimization", "enabled": True, "schedule": "@daily 06:30"},
    "bots/time_management/60_focus_session": {"description": "Pomodoro focus sessions", "enabled": True},
    # Ecommerce
    "bots/ecommerce/61_product_description": {"description": "Product descriptions for all platforms", "enabled": True, "schedule": "@weekly"},
    "bots/ecommerce/62_pricing_optimization": {"description": "Pricing strategy and optimization", "enabled": True, "schedule": "@monthly"},
    # Specialized
    "bots/specialized/63_course_creator":   {"description": "Online course curriculum design", "enabled": True, "schedule": "@monthly"},
    "bots/specialized/64_content_planning": {"description": "30-60-90 day content plans", "enabled": True, "schedule": "@monthly"},
    "bots/specialized/65_pricing_strategy": {"description": "Business pricing strategy", "enabled": True, "schedule": "@monthly"},
    "bots/specialized/66_podcast_generator": {"description": "Podcast episode scripts", "enabled": True, "schedule": "@weekly wed 09:00"},
    "bots/specialized/67_presentation_generator": {"description": "Presentation outlines and content", "enabled": True, "schedule": "@weekly"},
    "bots/specialized/68_designing_bot":    {"description": "Visual design briefs and prompts", "enabled": True, "schedule": "@weekly"},
    "bots/specialized/69_invoice_management": {"description": "Invoice creation and tracking", "enabled": True, "schedule": "@daily 08:00"},
    "bots/specialized/70_reporting_dashboard": {"description": "Weekly/monthly business reports", "enabled": True, "schedule": "@weekly mon 07:00"},
}

created = 0
for path, config in configs.items():
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    cfg_file = p / "config.json"
    if not cfg_file.exists():
        cfg_file.write_text(json.dumps(config, indent=2))
        created += 1

print(f"  ✓ {created} config files initialized")
PYEOF

ok "Bot configs initialized"

# ─── 9. Create FAQ for chatbot ────────────────────────────────────────────────
step "Creating FAQ knowledge base"
cat > bots/customer_support/30_faq_chatbot/faq.json << 'FAQEOF'
{
  "company": "WheellsVerse",
  "faqs": [
    {"q": "How do I get started?", "a": "Sign up at wheellsverse.com and you'll get a 14-day free trial with full access to all 70 bots."},
    {"q": "What is WheellsVerse?", "a": "WheellsVerse is an AI-powered automation platform with 70 autonomous bots that handle marketing, sales, writing, analytics, and more."},
    {"q": "What payment methods do you accept?", "a": "We accept Visa, Mastercard, American Express, PayPal, and all major credit cards via Stripe."},
    {"q": "Can I cancel anytime?", "a": "Yes, you can cancel your subscription anytime from your account settings. No long-term contracts."},
    {"q": "Do you offer refunds?", "a": "Yes, we have a 30-day money-back guarantee, no questions asked."},
    {"q": "How do I contact support?", "a": "Email support@wheellsverse.com or use our live chat. We respond within 24 hours."},
    {"q": "Do I need coding knowledge?", "a": "No coding required for most bots. For technical bots, basic Python knowledge helps but is not required."},
    {"q": "Can I run multiple bots at once?", "a": "Yes! The orchestrator runs bots in parallel. You can run all 70 bots simultaneously."},
    {"q": "What's your pricing?", "a": "Plans start at $47/month (Starter), $97/month (Pro), and $197/month (Agency). Annual plans save 30%."},
    {"q": "Is my data secure?", "a": "Yes. All data stays local on your machine unless you configure cloud integrations. We never store your API keys or content."}
  ]
}
FAQEOF
ok "FAQ knowledge base created"

# ─── 10. Create cron helper ───────────────────────────────────────────────────
step "Creating cron schedule helper"
cat > setup_cron.sh << 'CRONEOF'
#!/bin/bash
# Add WheellsVerse to macOS cron
# Run: bash setup_cron.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PYTHON="$SCRIPT_DIR/venv/bin/python3"
MAIN_PY="$SCRIPT_DIR/main.py"

# Daily morning run (9am) — marketing category
CRON_DAILY="0 9 * * * cd $SCRIPT_DIR && $VENV_PYTHON $MAIN_PY --category marketing >> $SCRIPT_DIR/logs/cron.log 2>&1"

# Weekly report (Monday 7am)
CRON_WEEKLY="0 7 * * 1 cd $SCRIPT_DIR && $VENV_PYTHON $MAIN_PY --run specialized/70_reporting_dashboard >> $SCRIPT_DIR/logs/cron.log 2>&1"

# Reminder check (every 30 min)
CRON_REMINDERS="*/30 * * * * cd $SCRIPT_DIR && $VENV_PYTHON $MAIN_PY --run assistant/55_reminder_bot >> $SCRIPT_DIR/logs/cron.log 2>&1"

echo "Adding cron jobs..."
(crontab -l 2>/dev/null; echo "$CRON_DAILY") | crontab -
(crontab -l 2>/dev/null; echo "$CRON_WEEKLY") | crontab -
(crontab -l 2>/dev/null; echo "$CRON_REMINDERS") | crontab -

echo "✅ Cron jobs added! View with: crontab -l"
CRONEOF
chmod +x setup_cron.sh
ok "Cron helper created"

# ─── 11. Create launch scripts ────────────────────────────────────────────────
step "Creating launch shortcuts"

cat > launch.sh << 'LAUNCHEOF'
#!/bin/bash
# Quick launcher
cd "$(dirname "${BASH_SOURCE[0]}")"
source venv/bin/activate
python3 main.py "$@"
LAUNCHEOF
chmod +x launch.sh

cat > dashboard.sh << 'DASHEOF'
#!/bin/bash
# Launch web dashboard
cd "$(dirname "${BASH_SOURCE[0]}")"
source venv/bin/activate
python3 main.py --dashboard --port 5050
DASHEOF
chmod +x dashboard.sh

ok "Launch scripts created"

# ─── 12. Final verification ───────────────────────────────────────────────────
step "Verifying installation"
python3 -c "import openai, rich, flask, schedule, requests; print('  ✓ Core packages OK')"
BOT_COUNT=$(find bots -name "bot.py" 2>/dev/null | wc -l | tr -d ' ')
echo "  ✓ Bot files found: $BOT_COUNT"
echo "  ✓ Logs directory: ./logs/"
echo "  ✓ Outputs directory: ./outputs/"

# ─── Done ─────────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}╔══════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}${BOLD}║        ✅  SETUP COMPLETE!                           ║${NC}"
echo -e "${GREEN}${BOLD}╚══════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${CYAN}NEXT STEPS:${NC}"
echo ""
echo -e "  ${YELLOW}1.${NC} Add your API key to .env:"
echo -e "     ${WHITE}nano .env${NC}  (set OPENAI_API_KEY=sk-...)"
echo ""
echo -e "  ${YELLOW}2.${NC} Launch interactive menu:"
echo -e "     ${WHITE}./launch.sh${NC}"
echo ""
echo -e "  ${YELLOW}3.${NC} Launch web dashboard:"
echo -e "     ${WHITE}./dashboard.sh${NC}"
echo -e "     Then open: ${WHITE}http://localhost:5050${NC}"
echo ""
echo -e "  ${YELLOW}4.${NC} Run a single bot:"
echo -e "     ${WHITE}./launch.sh --run marketing/01_content_generator${NC}"
echo ""
echo -e "  ${YELLOW}5.${NC} Run all marketing bots:"
echo -e "     ${WHITE}./launch.sh --category marketing${NC}"
echo ""
echo -e "  ${YELLOW}6.${NC} Set up auto-scheduling:"
echo -e "     ${WHITE}bash setup_cron.sh${NC}"
echo ""
echo -e "${CYAN}Need help? Email: wheelerjhonkevensd@gmail.com${NC}"
echo ""
