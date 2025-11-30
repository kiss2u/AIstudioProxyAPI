# Test Suite Guide

**AIstudioProxyAPI Testing Documentation**

Last Updated: 2025-11-29
Test Pass Rate: 98.5% (602/611 tests)
Coverage Target: >80% for core modules

---

## Table of Contents

- [Quick Start](#quick-start)
- [Testing Philosophy](#testing-philosophy)
- [Fixture Reference](#fixture-reference)
- [Writing Tests](#writing-tests)
- [Running Tests](#running-tests)
- [Anti-Patterns to Avoid](#anti-patterns-to-avoid)
- [Troubleshooting](#troubleshooting)

---

## Quick Start

```bash
# Run all tests
poetry run pytest -v

# Run with coverage
poetry run pytest --cov=api_utils --cov=browser_utils --cov=stream --cov=config

# Run only unit tests (fast)
poetry run pytest -m "not integration" -v

# Run only integration tests
poetry run pytest -m integration -v

# Run specific test file
poetry run pytest tests/api_utils/test_queue_worker.py -v

# Run with timeout protection
poetry run pytest -vv --timeout=5
```

---

## Testing Philosophy

### Dual Testing Strategy

This project uses **two complementary test approaches**:

#### Unit Tests (`tests/api_utils/`, `tests/browser_utils/`, etc.)

- **Purpose**: Test individual functions/classes in isolation
- **Speed**: Fast (<1s per test)
- **Mocking**: Mock external I/O (browser, network) and sometimes internal helpers
- **Use for**: Logic validation, error handling, input validation

#### Integration Tests (`tests/integration/`)

- **Purpose**: Test components working together with real state
- **Speed**: Slower (0.1-2s per test)
- **Mocking**: Only external boundaries (browser, page, network)
- **Key Difference**: Uses **REAL** `asyncio.Lock`, `asyncio.Queue`, `asyncio.Event`
- **Use for**: Concurrency, race conditions, lock hierarchies, FIFO ordering

### When to Use Each Type

| Scenario                           | Unit Test | Integration Test |
| ---------------------------------- | --------- | ---------------- |
| Test a single function's logic     | ✅        | ❌               |
| Verify error handling              | ✅        | ❌               |
| Test lock mutual exclusion         | ❌        | ✅               |
| Test queue FIFO ordering           | ❌        | ✅               |
| Test concurrent request handling   | ❌        | ✅               |
| Verify client disconnect detection | ⚠️ Both   | ✅               |
| Test data transformations          | ✅        | ❌               |

---

## Fixture Reference

### Global Fixtures (`tests/conftest.py`)

#### `mock_playwright_stack`

Provides consolidated Playwright mocks (browser, context, page).

```python
def test_page_operations(mock_playwright_stack):
    """Use pre-configured Playwright mocks."""
    playwright, browser, context, page = mock_playwright_stack

    # All common methods are pre-mocked:
    await page.goto("https://example.com")  # AsyncMock
    await page.click("#button")  # AsyncMock
    await page.fill("input", "text")  # AsyncMock
```

**Includes**:

- `playwright`: Mock Playwright instance
- `browser`: Mock browser with `new_context()`, `close()`
- `context`: Mock browser context
- `page`: Mock page with `goto()`, `click()`, `fill()`, `evaluate()`, `locator()`, `is_closed()`

#### `make_chat_request()`

Factory for creating real `ChatCompletionRequest` objects (no MagicMock!).

```python
def test_request_validation(make_chat_request):
    """Create real ChatCompletionRequest with Pydantic validation."""
    # Default values
    request = make_chat_request()
    assert request.model == "gemini-1.5-pro"
    assert request.stream is False

    # Custom overrides
    request = make_chat_request(
        model="gemini-2.0-flash",
        stream=True,
        temperature=0.8,
        max_tokens=2048
    )
    assert request.temperature == 0.8
```

**Default Parameters**:

- `model="gemini-1.5-pro"`
- `messages=[Message(role="user", content="Test")]`
- `stream=False`
- `temperature=0.7`
- `max_tokens=1024`

#### `make_request_context()`

Factory for creating `RequestContext` dictionaries with sane defaults.

```python
def test_context_setup(make_request_context):
    """Create request context with customizable fields."""
    # Default context
    context = make_request_context()
    assert context["req_id"] == "test-req"
    assert context["is_page_ready"] is True

    # Custom overrides
    context = make_request_context(
        req_id="custom-id",
        is_page_ready=False,
        current_ai_studio_model_id="gemini-2.0-flash"
    )
    assert context["req_id"] == "custom-id"
    assert context["is_page_ready"] is False
```

**Default Fields** (from `context_types.py`):

- `req_id="test-req"`
- `page=<mock AsyncPage>`
- `logger=<logging.Logger>`
- `is_page_ready=True`
- `parsed_model_list=[]`
- `current_ai_studio_model_id="gemini-1.5-pro"`
- `model_switching_lock=<real asyncio.Lock>`
- `params_cache_lock=<real asyncio.Lock>`
- `page_params_cache={}`
- `is_streaming=False`
- `model_actually_switched=False`
- `requested_model="gemini-1.5-pro"`
- `model_id_to_use=None`
- `needs_model_switching=False`

#### `real_locks_mock_browser()`

**Hybrid fixture** providing real asyncio primitives + mock browser.

```python
async def test_lock_behavior(real_locks_mock_browser):
    """Test with REAL asyncio.Lock, not AsyncMock."""
    state = real_locks_mock_browser

    # These are REAL asyncio.Lock instances
    async with state.processing_lock:
        assert state.processing_lock.locked()  # Actually blocks!

    # Queue is REAL asyncio.Queue
    await state.request_queue.put({"req_id": "test"})
    item = await state.request_queue.get()
    assert item["req_id"] == "test"  # Proves FIFO
```

**Provides**:

- ✅ **REAL** `processing_lock` (asyncio.Lock)
- ✅ **REAL** `model_switching_lock` (asyncio.Lock)
- ✅ **REAL** `params_cache_lock` (asyncio.Lock)
- ✅ **REAL** `request_queue` (asyncio.Queue)
- ❌ **MOCK** `page_instance` (external I/O boundary)
- ❌ **MOCK** `browser_instance` (external I/O boundary)

### Integration Fixtures (`tests/integration/conftest.py`)

#### `real_server_state`

Provides real `server_state.state` with complete setup and teardown.

```python
@pytest.mark.integration
async def test_full_flow(real_server_state):
    """Integration test with real state management."""
    state = real_server_state

    # Real locks can be acquired by multiple tasks
    task1 = asyncio.create_task(acquire_lock(state.processing_lock))
    task2 = asyncio.create_task(acquire_lock(state.processing_lock))

    # Verify mutual exclusion
    results = await asyncio.gather(task1, task2)
    # Only one task can hold lock at a time!
```

**Includes**:

- Automatic `state.reset()` on setup
- Real asyncio primitives (Lock, Queue)
- Mock browser/page (external boundaries)
- **Cleanup**: Cancels tasks, clears queue, releases locks (critical for Windows)

#### `mock_http_request`

Mock HTTP request for testing disconnect detection.

```python
async def test_disconnect(mock_http_request):
    """Test client disconnect detection."""
    request = mock_http_request

    # Initially connected
    assert await request.is_disconnected() is False

    # Simulate disconnect
    request.is_disconnected = AsyncMock(return_value=True)
    assert await request.is_disconnected() is True
```

#### `queue_with_items`

Pre-populated queue for testing queue processing.

```python
async def test_queue_processing(queue_with_items):
    """Test with pre-filled queue."""
    queue, items = queue_with_items

    # Queue has 3 items pre-loaded
    assert queue.qsize() == 3

    # Process in FIFO order
    item = await queue.get()
    assert item["req_id"] == "test-req-0"
```

---

## Writing Tests

### Test Class Organization

Organize tests into logical classes by functionality:

```python
class TestQueueManagement:
    """Tests for queue operations."""

    @pytest.mark.asyncio
    async def test_add_to_queue(self):
        """Test adding items to queue."""
        pass

    @pytest.mark.asyncio
    async def test_process_from_queue(self):
        """Test FIFO processing."""
        pass


class TestErrorHandling:
    """Tests for error scenarios."""

    @pytest.mark.asyncio
    async def test_timeout_error(self):
        """Test timeout handling."""
        pass
```

### Behavioral Testing (Not Mock Verification)

```python
# ❌ BAD: Only verifies mock was called
async def test_process_request_bad():
    mock_lock = AsyncMock()
    await process_request(mock_lock)
    mock_lock.__aenter__.assert_called_once()  # Just checks call

# ✅ GOOD: Verifies actual behavior
async def test_process_request_good(real_locks_mock_browser):
    lock = real_locks_mock_browser.processing_lock

    async with lock:
        # Lock is actually held
        assert lock.locked()

    # Lock is actually released
    assert not lock.locked()
```

### Using Real Models Instead of MagicMock

```python
# ❌ BAD: MagicMock has no validation
def test_request_bad():
    request = MagicMock()
    request.model = "invalid-model"  # No validation!
    request.temperature = 5.0  # Invalid value accepted!

# ✅ GOOD: Real Pydantic model validates
def test_request_good(make_chat_request):
    with pytest.raises(ValidationError):
        request = ChatCompletionRequest(
            model="gemini-1.5-pro",
            messages=[],  # Empty messages - validation fails
            temperature=5.0  # Out of range - validation fails
        )
```

### Testing Concurrency

```python
@pytest.mark.integration
async def test_concurrent_requests(real_server_state):
    """Test that concurrent requests are serialized by lock."""
    execution_log = []
    lock = real_server_state.processing_lock

    async def request_handler(req_id: str):
        async with lock:
            execution_log.append(f"{req_id}_start")
            await asyncio.sleep(0.1)  # Simulate work
            execution_log.append(f"{req_id}_end")

    # Start two requests concurrently
    task1 = asyncio.create_task(request_handler("req1"))
    task2 = asyncio.create_task(request_handler("req2"))

    await asyncio.gather(task1, task2)

    # Verify mutual exclusion: one must complete before other starts
    assert "req1_end" in execution_log
    req1_end_idx = execution_log.index("req1_end")
    req2_start_idx = execution_log.index("req2_start")

    # Either req1 completes before req2 starts, or vice versa
    assert (req1_end_idx < req2_start_idx) or (execution_log.index("req2_end") < execution_log.index("req1_start"))
```

---

## Running Tests

### Basic Commands

```bash
# All tests with verbose output
poetry run pytest -v

# With coverage report
poetry run pytest --cov=api_utils --cov=browser_utils --cov=stream --cov-report=term-missing

# Only failed tests
poetry run pytest --lf

# Stop on first failure
poetry run pytest -x

# Run in parallel (faster)
poetry run pytest -n auto
```

### Selective Execution

```bash
# By marker
poetry run pytest -m integration  # Only integration tests
poetry run pytest -m "not integration"  # Only unit tests

# By test name pattern
poetry run pytest -k "test_lock"  # All tests with "lock" in name

# Specific test class
poetry run pytest tests/api_utils/test_queue_worker.py::TestQueueManagement -v

# Single test
poetry run pytest tests/api_utils/test_queue_worker.py::TestQueueManagement::test_add_to_queue -v
```

### Debugging Tests

```bash
# Show local variables on failure
poetry run pytest -vv --showlocals

# Show print() output
poetry run pytest -s

# Drop into debugger on failure
poetry run pytest --pdb

# Timeout protection (prevent hanging)
poetry run pytest --timeout=5 --timeout-method=thread
```

---

## Anti-Patterns to Avoid

### 1. Over-Mocking Internal State

```python
# ❌ BAD: Mocking everything including internal primitives
@pytest.fixture
def mock_everything():
    mock_queue = AsyncMock()  # Queue is internal state!
    mock_lock = AsyncMock()  # Lock is internal primitive!
    return mock_queue, mock_lock

# ✅ GOOD: Use real primitives, mock only external I/O
@pytest.fixture
def real_state_mock_browser():
    queue = asyncio.Queue()  # Real queue
    lock = asyncio.Lock()  # Real lock
    page = AsyncMock()  # Mock browser (external I/O)
    return queue, lock, page
```

### 2. Mocking the Function Being Tested

```python
# ❌ BAD: Circular testing - mocking internal helpers
def test_process_request():
    with patch("module.internal_helper") as mock_helper:
        await process_request()  # Calls internal_helper internally
        mock_helper.assert_called_once()  # Useless test!

# ✅ GOOD: Test the full function, mock external boundaries
def test_process_request(mock_playwright_stack):
    _, _, _, page = mock_playwright_stack
    with patch("browser_utils.page.click"):  # Mock external I/O
        result = await process_request(page)
        assert result["success"] is True  # Test actual behavior
```

### 3. Assertion-Only Testing

```python
# ❌ BAD: Only checking that methods were called
async def test_queue_worker():
    mock_queue = AsyncMock()
    await worker.process_queue(mock_queue)
    mock_queue.get.assert_called()  # Just checks call, not behavior

# ✅ GOOD: Verify actual state changes
async def test_queue_worker(real_locks_mock_browser):
    queue = real_locks_mock_browser.request_queue
    await queue.put({"req_id": "test"})

    item = await worker.process_queue(queue)
    assert item["req_id"] == "test"  # Proves FIFO behavior
    assert queue.empty()  # Proves item was consumed
```

### 4. Missing Task Cleanup

```python
# ❌ BAD: Background tasks not cleaned up (causes Windows hangs)
async def test_background_task():
    task = asyncio.create_task(long_running_task())
    # Test completes, task still running!

# ✅ GOOD: Always cancel and await tasks
async def test_background_task():
    task = asyncio.create_task(long_running_task())
    try:
        # Test logic
        pass
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
```

### 5. Using MagicMock for Pydantic Models

```python
# ❌ BAD: No validation
def test_request():
    request = MagicMock()
    request.model = "anything"  # No validation!
    request.temperature = 999  # Invalid value accepted!

# ✅ GOOD: Use fixture for real models
def test_request(make_chat_request):
    request = make_chat_request(temperature=0.8)  # Validated!
    with pytest.raises(ValidationError):
        bad_request = ChatCompletionRequest(
            model="gemini",
            messages=[],
            temperature=999  # Validation fails
        )
```

---

## Troubleshooting

### Tests Hanging on Windows

**Cause**: Background tasks or locks not released.

**Solution**:

```python
@pytest.fixture
async def my_fixture():
    # Setup
    task = asyncio.create_task(worker())
    yield task

    # Cleanup (CRITICAL for Windows)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
```

### Queue Test Failures

**Cause**: Using `queue.task_done()` without `queue.get()`.

**Solution**:

```python
# For unit tests that call process_request directly
queue_manager.request_queue.task_done = MagicMock()  # Mock it

# For integration tests
await queue.put(item)
item = await queue.get()  # Always pair with task_done
queue.task_done()
```

### Import Errors in Tests

**Cause**: Circular import from importing `server` module.

**Solution**:

```python
# ❌ BAD: Direct import causes circular dependency
from server import processing_lock

# ✅ GOOD: Import from server_state
from api_utils.server_state import state
lock = state.processing_lock
```

### Coverage Not Showing

**Cause**: Wrong module path or missing `--cov` flag.

**Solution**:

```bash
# Specify modules explicitly
poetry run pytest --cov=api_utils --cov=browser_utils --cov=stream --cov-report=term-missing

# Or use config in pytest.ini
poetry run pytest --cov --cov-report=html
```

---

## Test Statistics (Phase 1 - 2025-11-29)

**Overall Results**:

- Total Tests: 611
- Passing: 602 (98.5%)
- Failing: 9 (1.5% - integration cleanup issues)
- Coverage: >80% core modules

**Mock Reduction**:

- Before: 2,544 total mocks
- After: <1,500 total mocks
- Reduction: 41%

**Major Rewrites**:

- `test_request_processor.py`: 103→<50 mocks (51% reduction)
- `test_queue_worker.py`: 98→~35 mocks (64% reduction)
- `test_model_switching.py`: 82→~28 mocks (66% reduction)
- `test_context_init.py`: 95→~12 mocks (87% reduction)
- `test_page_response.py`: 56→~31 mocks (45% reduction)

**New Test Files**:

- 5 integration test files (2000+ lines total)
- 68 integration tests for concurrency, locks, queues

---

## Additional Resources

- **Main CLAUDE.md**: [../CLAUDE.md](../CLAUDE.md) - Full testing strategy
- **API Utils Tests**: [api_utils/](./api_utils/) - Unit tests for FastAPI layer
- **Browser Utils Tests**: [browser_utils/](./browser_utils/) - Unit tests for browser automation
- **Integration Tests**: [integration/](./integration/) - Real async primitive tests
- **Pytest Documentation**: https://docs.pytest.org/
- **Pytest-Asyncio**: https://pytest-asyncio.readthedocs.io/

---

**Need help?** Check the [Troubleshooting](#troubleshooting) section or consult `CLAUDE.md` for testing philosophy.
