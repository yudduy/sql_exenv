#!/bin/bash
# Quick Setup Script for Agentic DBA

set -e

echo "=================================="
echo "Agentic DBA - Quick Setup"
echo "=================================="

# Check Python version
echo ""
echo "Checking Python version..."
python_version=$(python3 --version 2>&1 | awk '{print $2}')
echo "✓ Found Python $python_version"

# Install dependencies
echo ""
echo "Installing dependencies..."
pip install -r requirements.txt

echo ""
echo "=================================="
echo "Setup Complete!"
echo "=================================="

echo ""
echo "Next Steps:"
echo ""
echo "1. Set your Anthropic API key (optional - can use mock mode):"
echo "   export ANTHROPIC_API_KEY='your-key-here'"
echo ""
echo "2. Test with mock mode (no API key needed):"
echo "   python test_demo.py"
echo ""
echo "3. Configure for Claude Desktop:"
echo "   See README.md for claude_desktop_config.json setup"
echo ""
echo "4. Test with real database:"
echo "   export TEST_DB_URL='postgresql://user:pass@localhost/dbname'"
echo "   python mcp_server.py test"
echo ""
echo "📚 Read the full documentation in README.md"
