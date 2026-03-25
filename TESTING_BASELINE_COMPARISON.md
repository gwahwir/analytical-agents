# Baseline Comparison Testing Guide

## ✅ Automated Tests: PASSED (9/9)

All automated tests passed successfully:
- ✅ Baseline comparison node invocation
- ✅ Skip logic when no baselines
- ✅ Input format validation
- ✅ Error handling
- ✅ Final synthesis integration
- ✅ Graph wiring verification

## Manual Testing Steps

### Prerequisites

1. **Start the full stack:**
   ```bash
   # Option 1: Docker (recommended)
   OPENAI_API_KEY=sk-... docker compose up

   # Option 2: Local development
   bash run-local.sh
   ```

2. **Verify specialist is registered:**
   ```bash
   # Check that baseline-comparison specialist is available
   curl http://localhost:8006/ | jq

   # Check agent card
   curl http://localhost:8006/baseline-comparison/.well-known/agent-card.json | jq
   ```

### Test Case 1: Basic Baseline Comparison (API)

**Scenario:** Submit a task with baseline assessments and verify change detection.

```bash
# Submit task to Lead Analyst with baselines
curl -X POST http://localhost:8000/agents/lead-analyst-a/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "input": "Analyze current South China Sea security dynamics. Focus on recent naval activities and diplomatic tensions.",
    "baselines": "Prior assessment (3 months ago): Tensions were moderate. US-China military encounters were infrequent (1-2 per quarter). ASEAN maintained unified stance on freedom of navigation. Risk of escalation was assessed as low to moderate.",
    "key_questions": "Has the risk assessment changed? Are there new patterns in military activities? Is ASEAN unity holding?"
  }'

# Response will include task_id
# {"task_id": "task-abc123", "state": "submitted"}

# Poll for completion (replace with actual task_id)
curl http://localhost:8000/tasks/task-abc123 | jq

# Check that output includes baseline comparison
curl http://localhost:8000/tasks/task-abc123 | jq '.output' | grep -i "baseline"
```

**Expected Output:**
- Task completes successfully
- Output includes "baseline_comparison" in node_outputs
- Final synthesis mentions baseline changes (confirmed/challenged/updated)

### Test Case 2: No Baselines Provided (Skip Logic)

**Scenario:** Verify baseline comparison is skipped when no baselines provided.

```bash
# Submit task WITHOUT baselines
curl -X POST http://localhost:8000/agents/lead-analyst-a/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "input": "Analyze South China Sea security dynamics.",
    "key_questions": "What are the key risks?"
  }'

# Poll for task completion
# curl http://localhost:8000/tasks/task-xyz789 | jq

# Verify baseline_comparison is empty in node_outputs
# curl http://localhost:8000/tasks/task-xyz789 | jq '.node_outputs.call_baseline_comparison'
```

**Expected Output:**
- Task completes successfully
- `node_outputs.call_baseline_comparison` is empty or contains `""`
- Final synthesis does NOT include baseline comparison section

### Test Case 3: Dashboard Testing (Recommended)

**Scenario:** Use the dashboard for visual testing with real LLM responses.

1. **Open Dashboard:**
   ```
   http://localhost:5173
   ```

2. **Navigate to Lead Analyst A:**
   - Click on "lead-analyst-a" in the agents list

3. **Submit Task with Baselines:**
   - **Scenario / Question:**
     ```
     Analyze the impact of recent chip export controls on US-China tech relations.
     ```

   - **Current Baseline Assessments:**
     ```
     Prior assessment (6 months ago):
     - US export controls were narrowly targeted at specific chip technologies
     - China was developing domestic alternatives but 3-5 years behind
     - Economic decoupling was partial and concentrated in semiconductors
     - Tech cooperation continued in non-sensitive areas (climate tech, biotech)
     ```

   - **Key Questions:**
     ```
     - Have export controls expanded beyond semiconductors?
     - Has China accelerated domestic chip development?
     - Is tech decoupling becoming more comprehensive?
     - Are there signs of cooperation breakdown in non-sensitive areas?
     ```

4. **Monitor Execution:**
   - Watch the task progress through nodes in real-time
   - Verify `call_baseline_comparison` node executes after `call_ach_red_team`

5. **Review Output:**
   - Click on completed task to see full output
   - Look for "Baseline Change Summary" section in final synthesis
   - Check for structured change detection (confirmed/challenged/updated/stable/new insights)

**Expected Output:**
```json
{
  "synthesis": "...",
  "perspective_comparison": {...},
  "baseline_change_summary": {
    "confirmed": ["Some baseline points supported by new analysis"],
    "challenged": ["Some baseline points contradicted"],
    "updated": ["Some baseline points refined"],
    "stable": ["Core dynamics that remain unchanged"],
    "new_insights": ["New factors not in original baseline"]
  },
  "key_takeaways": [...],
  "recommended_actions": [...]
}
```

### Test Case 4: Specialist Direct Testing

**Scenario:** Test baseline-comparison specialist directly (isolated from Lead Analyst).

```bash
# Test specialist directly via A2A
curl -X POST http://localhost:8006/baseline-comparison/ \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "method": "message/send",
    "params": {
      "message": {
        "text": "## BASELINE ASSESSMENTS:\n\nPrior assessment: Economic growth was strong at 6%, inflation was moderate at 2%, unemployment was low at 4%.\n\n---\n## NEW ANALYSIS:\n\nCurrent analysis: Economic growth has slowed to 3% due to global headwinds. Inflation has risen to 4% driven by energy prices. Unemployment remains stable at 4%.\n\n---\n## YOUR TASK:\n\nCompare the new analysis above against the baseline assessments. Identify what has been confirmed, challenged, updated, or what remains stable.",
        "metadata": {}
      }
    },
    "id": 1
  }' | jq
```

**Expected Output:**
```json
{
  "jsonrpc": "2.0",
  "result": {
    "status": {
      "code": 1,
      "message": {
        "parts": [
          {
            "text": "{\"framework_name\": \"Baseline Change Detection\", \"summary\": \"...\", \"baseline_changes\": {\"confirmed\": [...], \"challenged\": [...], \"updated\": [...], \"stable\": [...], \"new_insights\": [...]}, ...}"
          }
        ]
      }
    }
  },
  "id": 1
}
```

### Test Case 5: Error Handling

**Scenario:** Verify graceful error handling when specialist is unavailable.

```bash
# Stop specialist agent
docker compose stop specialist-agent

# Submit task with baselines
curl -X POST http://localhost:8000/agents/lead-analyst-a/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "input": "Analyze situation",
    "baselines": "Prior assessment: X was true"
  }'

# Check task completes despite specialist failure
# Verify error is logged but task doesn't fail
```

**Expected Behavior:**
- Task completes (doesn't crash)
- Error logged: `"[Error calling baseline_comparison: ...]"`
- Final synthesis continues without baseline comparison

### Verification Checklist

- [ ] All 9 automated tests pass
- [ ] Specialist agent registered at `/baseline-comparison/`
- [ ] Agent card returns correct metadata
- [ ] Task with baselines produces baseline comparison output
- [ ] Task without baselines skips baseline comparison
- [ ] Final synthesis includes baseline change summary when provided
- [ ] Dashboard shows `call_baseline_comparison` node in graph
- [ ] Node executes in correct sequence (after ACH, before final_synthesis)
- [ ] Direct specialist testing returns structured JSON
- [ ] Error handling works when specialist unavailable

## Troubleshooting

### Issue: Specialist not found (404)

**Solution:**
```bash
# Restart specialist agent
docker compose restart specialist-agent

# Verify specialist is mounted
curl http://localhost:8006/ | jq '.specialists[] | select(.type_id == "baseline-comparison")'
```

### Issue: baseline_comparison field empty despite baselines provided

**Check:**
1. Verify baselines field is non-empty in input
2. Check control plane logs for errors
3. Verify `SPECIALIST_AGENT_URL` environment variable

```bash
# Check logs
docker compose logs specialist-agent | grep baseline
docker compose logs lead-analyst | grep baseline
```

### Issue: Tests fail with import errors

**Solution:**
```bash
# Reinstall dependencies
pip install -r requirements.txt

# Run tests with more verbose output
python -m pytest tests/test_baseline_comparison.py -vv --tb=short
```

## Success Criteria

✅ **Phase 1 Complete When:**
- All automated tests pass
- Specialist registers successfully on startup
- Tasks with baselines produce structured change detection
- Tasks without baselines skip gracefully
- Final synthesis integrates baseline changes
- Dashboard shows new node in pipeline
- Documentation reflects new capability

## Next Steps (Phase 2)

After validating Phase 1:
1. Add PostgreSQL indices for historical queries
2. Implement `/agents/{agent_id}/tasks/history` endpoint
3. Build multi-document aggregation logic
4. Test time-series baseline comparison across multiple reports
