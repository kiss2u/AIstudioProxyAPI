"""
Queue Worker Module
Handles tasks in the request queue.
"""

import asyncio
import time
import logging
from typing import Any, Dict, Optional, Tuple, List, Set
from fastapi import HTTPException
from asyncio import Queue, Lock, Future, Event

from .error_utils import (
    client_disconnected,
    client_cancelled,
    processing_timeout,
    server_error,
)

class QueueManager:
    def __init__(self):
        self.logger = logging.getLogger("queue_worker")
        self.was_last_request_streaming = False
        self.last_request_completion_time = 0.0
        
        # These will be initialized from server.py or created if missing
        self.request_queue: Optional[Queue] = None
        self.processing_lock: Optional[Lock] = None
        self.model_switching_lock: Optional[Lock] = None
        self.params_cache_lock: Optional[Lock] = None
        
        # Context for cleanup
        self.current_submit_btn_loc = None
        self.current_client_disco_checker = None
        self.current_completion_event = None
        self.current_req_id = None

    def initialize_globals(self):
        """Initialize global variables from server module or create new ones."""
        import server
        
        # Use server's logger if available, otherwise keep local one
        if hasattr(server, 'logger'):
            self.logger = server.logger
            
        self.logger.info("--- Queue Worker Initializing ---")

        if server.request_queue is None:
            self.logger.info("Initializing request_queue...")
            server.request_queue = Queue()
        self.request_queue = server.request_queue

        if server.processing_lock is None:
            self.logger.info("Initializing processing_lock...")
            server.processing_lock = Lock()
        self.processing_lock = server.processing_lock

        if server.model_switching_lock is None:
            self.logger.info("Initializing model_switching_lock...")
            server.model_switching_lock = Lock()
        self.model_switching_lock = server.model_switching_lock

        if server.params_cache_lock is None:
            self.logger.info("Initializing params_cache_lock...")
            server.params_cache_lock = Lock()
        self.params_cache_lock = server.params_cache_lock

    async def check_queue_disconnects(self):
        """Check for disconnected clients in the queue."""
        if not self.request_queue:
            return

        queue_size = self.request_queue.qsize()
        if queue_size == 0:
            return

        checked_count = 0
        items_to_requeue = []
        processed_ids = set()

        # Limit check to 10 items or queue size
        limit = min(queue_size, 10)
        
        while checked_count < limit:
            try:
                item = self.request_queue.get_nowait()
                item_req_id = item.get("req_id", "unknown")

                if item_req_id in processed_ids:
                    items_to_requeue.append(item)
                    continue

                processed_ids.add(item_req_id)

                if not item.get("cancelled", False):
                    item_http_request = item.get("http_request")
                    if item_http_request:
                        try:
                            if await item_http_request.is_disconnected():
                                self.logger.info(
                                    f"[{item_req_id}] (Worker Queue Check) Client disconnected, marking cancelled."
                                )
                                item["cancelled"] = True
                                item_future = item.get("result_future")
                                if item_future and not item_future.done():
                                    item_future.set_exception(
                                        client_disconnected(
                                            item_req_id,
                                            "Client disconnected while queued.",
                                        )
                                    )
                        except Exception as check_err:
                            self.logger.error(
                                f"[{item_req_id}] (Worker Queue Check) Error checking disconnect: {check_err}"
                            )

                items_to_requeue.append(item)
                checked_count += 1
            except asyncio.QueueEmpty:
                break

        for item in items_to_requeue:
            await self.request_queue.put(item)

    async def get_next_request(self) -> Optional[Dict[str, Any]]:
        """Get the next request from the queue with timeout."""
        if not self.request_queue:
            await asyncio.sleep(1)
            return None
            
        try:
            return await asyncio.wait_for(self.request_queue.get(), timeout=5.0)
        except asyncio.TimeoutError:
            return None

    async def handle_streaming_delay(self, req_id: str, is_streaming_request: bool):
        """Handle delay between streaming requests."""
        current_time = time.time()
        if (
            self.was_last_request_streaming
            and is_streaming_request
            and (current_time - self.last_request_completion_time < 1.0)
        ):
            delay_time = max(0.5, 1.0 - (current_time - self.last_request_completion_time))
            self.logger.info(
                f"[{req_id}] (Worker) Sequential streaming request, adding {delay_time:.2f}s delay..."
            )
            await asyncio.sleep(delay_time)

    async def process_request(self, request_item: Dict[str, Any]):
        """Process a single request item."""
        req_id = request_item["req_id"]
        request_data = request_item["request_data"]
        http_request = request_item["http_request"]
        result_future = request_item["result_future"]

        # 1. Check cancellation
        if request_item.get("cancelled", False):
            self.logger.info(f"[{req_id}] (Worker) Request cancelled, skipping.")
            if not result_future.done():
                result_future.set_exception(client_cancelled(req_id, "Request cancelled by user"))
            if self.request_queue:
                self.request_queue.task_done()
            return

        is_streaming_request = request_data.stream
        self.logger.info(
            f"[{req_id}] (Worker) Dequeued request. Mode: {'Streaming' if is_streaming_request else 'Non-streaming'}"
        )

        # 2. Initial Connection Check
        from api_utils.request_processor import _check_client_connection
        if not await _check_client_connection(req_id, http_request):
            self.logger.info(f"[{req_id}] (Worker) ✅ Client disconnected before processing.")
            if not result_future.done():
                result_future.set_exception(
                    HTTPException(status_code=499, detail=f"[{req_id}] Client disconnected before processing")
                )
            if self.request_queue:
                self.request_queue.task_done()
            return

        # 3. Streaming Delay
        await self.handle_streaming_delay(req_id, is_streaming_request)

        # 4. Connection Check before Lock
        if not await _check_client_connection(req_id, http_request):
            self.logger.info(f"[{req_id}] (Worker) ✅ Client disconnected while waiting.")
            if not result_future.done():
                result_future.set_exception(
                    HTTPException(status_code=499, detail=f"[{req_id}] Client disconnected")
                )
            if self.request_queue:
                self.request_queue.task_done()
            return

        self.logger.info(f"[{req_id}] (Worker) Waiting for processing lock...")
        
        if not self.processing_lock:
             self.logger.error(f"[{req_id}] Processing lock is None!")
             if not result_future.done():
                 result_future.set_exception(server_error(req_id, "Internal error: Processing lock missing"))
             if self.request_queue:
                 self.request_queue.task_done()
             return

        async with self.processing_lock:
            self.logger.info(f"[{req_id}] (Worker) Acquired processing lock.")
            
            # 5. Final Connection Check inside Lock
            if not await _check_client_connection(req_id, http_request):
                self.logger.info(f"[{req_id}] (Worker) ✅ Client disconnected inside lock.")
                if not result_future.done():
                    result_future.set_exception(
                        HTTPException(status_code=499, detail=f"[{req_id}] Client disconnected")
                    )
            elif result_future.done():
                self.logger.info(f"[{req_id}] (Worker) Future already done. Skipping.")
            else:
                await self._execute_request_logic(req_id, request_data, http_request, result_future)

            # 6. Cleanup / Post-processing (Clear Stream Queue & Chat History)
            await self._cleanup_after_processing(req_id)

            self.logger.info(f"[{req_id}] (Worker) Released processing lock.")

        # Update state for next iteration
        self.was_last_request_streaming = is_streaming_request
        self.last_request_completion_time = time.time()
        if self.request_queue:
            self.request_queue.task_done()

    async def _execute_request_logic(self, req_id, request_data, http_request, result_future):
        """Execute the actual request processing logic."""
        try:
            from api_utils import _process_request_refactored
            
            # Store these for cleanup usage if needed
            self.current_submit_btn_loc = None
            self.current_client_disco_checker = None
            self.current_completion_event = None
            self.current_req_id = req_id

            returned_value = await _process_request_refactored(
                req_id, request_data, http_request, result_future
            )

            completion_event = None
            submit_btn_loc = None
            client_disco_checker = None
            current_request_was_streaming = False

            if isinstance(returned_value, tuple) and len(returned_value) == 3:
                completion_event, submit_btn_loc, client_disco_checker = returned_value
                if completion_event is not None:
                    current_request_was_streaming = True
                    self.logger.info(f"[{req_id}] (Worker) Stream info received.")
                else:
                    self.logger.info(f"[{req_id}] (Worker) Tuple received but completion_event is None.")
            elif returned_value is None:
                self.logger.info(f"[{req_id}] (Worker) Non-stream completion (None).")
            else:
                self.logger.warning(f"[{req_id}] (Worker) Unexpected return type: {type(returned_value)}")

            # Store for cleanup
            self.current_submit_btn_loc = submit_btn_loc
            self.current_client_disco_checker = client_disco_checker
            self.current_completion_event = completion_event

            await self._monitor_completion(
                req_id, http_request, result_future, completion_event, 
                submit_btn_loc, client_disco_checker, current_request_was_streaming
            )

        except Exception as process_err:
            self.logger.error(f"[{req_id}] (Worker) Execution error: {process_err}")
            if not result_future.done():
                result_future.set_exception(server_error(req_id, f"Request processing error: {process_err}"))

    async def _monitor_completion(self, req_id, http_request, result_future, completion_event, 
                                submit_btn_loc, client_disco_checker, current_request_was_streaming):
        """Monitor for completion and handle disconnects."""
        from api_utils.client_connection import (
            enhanced_disconnect_monitor,
            non_streaming_disconnect_monitor,
        )
        from server import RESPONSE_COMPLETION_TIMEOUT

        disconnect_monitor_task = None
        try:
            if completion_event:
                self.logger.info(f"[{req_id}] (Worker) Waiting for stream completion...")
                disconnect_monitor_task = asyncio.create_task(
                    enhanced_disconnect_monitor(req_id, http_request, completion_event, self.logger)
                )
                
                await asyncio.wait_for(
                    completion_event.wait(),
                    timeout=RESPONSE_COMPLETION_TIMEOUT / 1000 + 60,
                )
            else:
                self.logger.info(f"[{req_id}] (Worker) Waiting for non-stream completion...")
                disconnect_monitor_task = asyncio.create_task(
                    non_streaming_disconnect_monitor(req_id, http_request, result_future, self.logger)
                )
                
                await asyncio.wait_for(
                    asyncio.shield(result_future),
                    timeout=RESPONSE_COMPLETION_TIMEOUT / 1000 + 60,
                )

            # Check if client disconnected early
            client_disconnected_early = False
            if disconnect_monitor_task.done():
                try:
                    client_disconnected_early = disconnect_monitor_task.result()
                except Exception:
                    pass
            
            self.logger.info(f"[{req_id}] (Worker) Processing complete. Early disconnect: {client_disconnected_early}")

            if not client_disconnected_early and submit_btn_loc and client_disco_checker and completion_event:
                await self._handle_post_stream_button(req_id, submit_btn_loc, client_disco_checker, completion_event)

        except asyncio.TimeoutError:
            self.logger.warning(f"[{req_id}] (Worker) ⚠️ Processing timed out.")
            if not result_future.done():
                result_future.set_exception(
                    processing_timeout(req_id, "Processing timed out waiting for completion.")
                )
        except Exception as ev_wait_err:
            self.logger.error(f"[{req_id}] (Worker) ❌ Error waiting for completion: {ev_wait_err}")
            if not result_future.done():
                result_future.set_exception(server_error(req_id, f"Error waiting for completion: {ev_wait_err}"))
        finally:
            if disconnect_monitor_task and not disconnect_monitor_task.done():
                disconnect_monitor_task.cancel()
                try:
                    await disconnect_monitor_task
                except asyncio.CancelledError:
                    pass

    async def _handle_post_stream_button(self, req_id, submit_btn_loc, client_disco_checker, completion_event):
        """Handle the submit button state after streaming."""
        self.logger.info(f"[{req_id}] (Worker) Handling post-stream button state...")
        try:
            from server import page_instance
            from browser_utils.page_controller import PageController

            if page_instance:
                page_controller = PageController(page_instance, self.logger, req_id)
                await page_controller.ensure_generation_stopped(client_disco_checker)
            else:
                self.logger.warning(f"[{req_id}] (Worker) page_instance is None during button handling")

        except Exception as e_ensure_stop:
            self.logger.warning(f"[{req_id}] ⚠️ Post-stream button handling error: {e_ensure_stop}")
            # Use comprehensive snapshot for better debugging
            from browser_utils.debug_utils import (
                save_comprehensive_snapshot,
            )
            from server import page_instance
            from config import PROMPT_TEXTAREA_SELECTOR
            import os

            if page_instance:
                await save_comprehensive_snapshot(
                    page=page_instance,
                    error_name="stream_post_submit_button_handling_timeout",
                    req_id=req_id,
                    error_stage="流式响应后按钮状态处理",
                    additional_context={
                        "headless_mode": os.environ.get(
                            "HEADLESS", "true"
                        ).lower()
                        == "true",
                        "completion_event_set": completion_event.is_set()
                        if completion_event
                        else None,
                        "error_type": type(
                            e_ensure_stop
                        ).__name__,
                        "error_message": str(e_ensure_stop),
                    },
                    locators={
                        "submit_button": submit_btn_loc,
                        "input_field": page_instance.locator(
                            PROMPT_TEXTAREA_SELECTOR
                        ),
                    },
                    error_exception=e_ensure_stop,
                )

    async def _cleanup_after_processing(self, req_id):
        """Clean up stream queue and chat history."""
        try:
            from api_utils import clear_stream_queue
            await clear_stream_queue()

            # Clear chat history if we have the necessary context
            if getattr(self, 'current_submit_btn_loc', None) and getattr(self, 'current_client_disco_checker', None):
                from server import page_instance, is_page_ready
                
                if page_instance and is_page_ready:
                    from browser_utils.page_controller import PageController
                    page_controller = PageController(page_instance, self.logger, req_id)
                    
                    self.logger.info(f"[{req_id}] (Worker) Clearing chat history...")
                    await page_controller.clear_chat_history(self.current_client_disco_checker)
                    self.logger.info(f"[{req_id}] (Worker) ✅ Chat history cleared.")
        except Exception as clear_err:
            self.logger.error(f"[{req_id}] (Worker) Cleanup error: {clear_err}", exc_info=True)

async def queue_worker() -> None:
    """Main queue worker entry point."""
    manager = QueueManager()
    manager.initialize_globals()
    
    logger = manager.logger
    logger.info("--- Queue Worker Started ---")

    while True:
        try:
            await manager.check_queue_disconnects()
            
            request_item = await manager.get_next_request()
            if request_item:
                await manager.process_request(request_item)
                
        except asyncio.CancelledError:
            logger.info("--- Queue Worker Cancelled ---")
            break
        except Exception as e:
            logger.error(f"(Worker) ❌ Unexpected error in main loop: {e}", exc_info=True)
            await asyncio.sleep(1) # Prevent tight loop on error

    logger.info("--- Queue Worker Stopped ---")
