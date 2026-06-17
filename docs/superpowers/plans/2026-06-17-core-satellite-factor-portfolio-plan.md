# Core-Satellite Factor Portfolio Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Milestone 2 factor portfolio construction as an independent portfolio layer.

**Architecture:** Add `backtest/factor_portfolio.py` as the only new portfolio layer. Strategies provide signals; the portfolio constructor converts core and satellite signals into target weights with 70/30 allocation, turnover control, and simple inverse-volatility risk budgeting. Add a synthetic example report to compare core, satellite, and combined portfolio behavior.

**Tech Stack:** Python, pandas, existing analysis utilities, pytest.

---

### Task 1: Core-Satellite Portfolio Layer

**Files:**
- Create: `backtest/factor_portfolio.py`
- Test: `tests/test_factor_portfolio.py`

- [ ] Write tests for allocation, turnover cap, and risk budgeting.
- [ ] Implement `CoreSatelliteFactorPortfolio`.
- [ ] Verify `pytest tests/test_factor_portfolio.py`.

### Task 2: Milestone 2 Example and Report

**Files:**
- Create: `examples/milestone2_core_satellite_portfolio.py`
- Create: `reports/milestone2_core_satellite_portfolio.md`
- Test: `tests/test_milestone2_core_satellite_example.py`

- [ ] Write example test for comparison output.
- [ ] Implement synthetic comparison of core-only, satellite-only, and core-satellite curves.
- [ ] Verify milestone-specific tests and full test suite.
