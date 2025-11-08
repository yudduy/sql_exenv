# SQL Optimization Examples Makefile
# Convenient commands for setting up and running examples

.PHONY: setup teardown clean test interactive help

# Default database name
DB_NAME ?= sql_examples
DB_USER ?= postgres
DB_HOST ?= localhost
DB_PORT ?= 5432

# Database connection string
DB_CONNECTION = postgresql://$(DB_USER)@$(DB_HOST):$(DB_PORT)/$(DB_NAME)

help:
	@echo "SQL Optimization Examples - Available Commands:"
	@echo ""
	@echo "  setup         - Set up the example database"
	@echo "  teardown      - Remove all example tables"
	@echo "  clean         - Drop the entire database"
	@echo "  test          - Run sample query optimizations"
	@echo "  interactive   - Start interactive optimization mode"
	@echo "  help          - Show this help message"
	@echo ""
	@echo "Variables:"
	@echo "  DB_NAME       - Database name (default: sql_examples)"
	@echo "  DB_USER       - Database user (default: postgres)"
	@echo "  DB_HOST       - Database host (default: localhost)"
	@echo "  DB_PORT       - Database port (default: 5432)"
	@echo ""
	@echo "Examples:"
	@echo "  make setup DB_NAME=test_db"
	@echo "  make interactive DB_USER=myuser"

setup:
	@echo "Setting up example database: $(DB_NAME)"
	@createdb $(DB_NAME) 2>/dev/null || echo "Database $(DB_NAME) already exists"
	python scripts/setup_database.py --dbname $(DB_NAME) --user $(DB_USER) --host $(DB_HOST) --port $(DB_PORT)
	@echo "Database setup complete!"

teardown:
	@echo "Tearing down example database: $(DB_NAME)"
	python scripts/setup_database.py --teardown --dbname $(DB_NAME) --user $(DB_USER) --host $(DB_HOST) --port $(DB_PORT)
	@echo "Database teardown complete!"

clean:
	@echo "Dropping database: $(DB_NAME)"
	@dropdb $(DB_NAME) 2>/dev/null || echo "Database $(DB_NAME) does not exist"
	@echo "Database dropped!"

test:
	@echo "Running sample query optimizations"
	python scripts/run_examples.py --db-connection $(DB_CONNECTION) --file queries/sample_queries.sql

interactive:
	@echo "Starting interactive optimization mode"
	python scripts/run_examples.py --db-connection $(DB_CONNECTION) --interactive

test-real:
	@echo "Running optimizations with real LLM"
	python scripts/run_examples.py --db-connection $(DB_CONNECTION) --file queries/test_queries.sql --real

test-hypopg:
	@echo "Running optimizations with HypoPG proof"
	python scripts/run_examples.py --db-connection $(DB_CONNECTION) --file queries/test_queries.sql --use-hypopg

install-deps:
	@echo "Installing Python dependencies"
	pip install psycopg2-binary anthropic mcp pydantic sqlparse

# Quick demo that sets up and runs a test
demo: setup test
	@echo ""
	@echo "Demo complete! Try 'make interactive' to explore further."
