"""
upstox_ws_client.py - WebSocket client for Upstox (renamed to avoid conflicts)
"""

import asyncio
import json
import ssl
import requests
import logging
import time
from google.protobuf.json_format import MessageToDict
import MarketDataFeedV3_pb2 as pb

# FIXED: Import from the actual upstox-python-sdk package
import upstox_client as upstox_sdk
from websockets.asyncio.client import connect as ws_connect
from websockets.exceptions import ConnectionClosed

logger = logging.getLogger(__name__)


class UpstoxWebSocketClient:
    """Enhanced WebSocket Client with Reconnection and Validation"""
    
    def __init__(self, access_token, instruments, mode='full_d30', on_message_callback=None):
        self.access_token = access_token
        self.instruments = instruments
        self.mode = mode
        self.on_message_callback = on_message_callback
        self.websocket = None
        self.running = False
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 10
        self.reconnect_delay = 5  # seconds
        self.last_heartbeat = time.time()
        
        # FIXED: Use the SDK with alias
        self.configuration = upstox_sdk.Configuration()
        self.configuration.access_token = access_token
        
        logger.info(f"WebSocket client initialized for {len(instruments)} instruments")
    
    def validate_order_params(self, symbol, transaction_type, quantity, price):
        """Validate order parameters before placing order"""
        errors = []
        
        if not symbol or not isinstance(symbol, str):
            errors.append("Invalid symbol")
        
        if transaction_type not in ['BUY', 'SELL']:
            errors.append(f"Invalid transaction_type: {transaction_type}")
        
        if not isinstance(quantity, int) or quantity <= 0:
            errors.append(f"Invalid quantity: {quantity}")
        
        if price is not None:
            if not isinstance(price, (int, float)) or price <= 0:
                errors.append(f"Invalid price: {price}")
        
        return errors
    
    def get_market_feed_authorization(self):
        """Get WebSocket authorization"""
        try:
            headers = {
                'Accept': 'application/json',
                'Authorization': f'Bearer {self.access_token}'
            }
            url = 'https://api.upstox.com/v3/feed/market-data-feed/authorize'
            response = requests.get(url=url, headers=headers, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logger.error(f"Authorization error: {e}", exc_info=True)
            raise
    
    def decode_protobuf(self, buffer):
        """Decode protobuf message"""
        try:
            feed_response = pb.FeedResponse()
            feed_response.ParseFromString(buffer)
            return MessageToDict(feed_response)
        except Exception as e:
            logger.error(f"Protobuf decode error: {e}", exc_info=True)
            return None
    
    def connect(self):
        """Start WebSocket connection"""
        asyncio.run(self._async_connect())
    
    async def _async_connect(self):
        """Async WebSocket connection with reconnection logic"""
        
        while self.reconnect_attempts < self.max_reconnect_attempts:
            try:
                # Use default SSL context (secure)
                ssl_context = ssl.create_default_context()
                
                auth_response = self.get_market_feed_authorization()
                ws_url = auth_response['data']['authorized_redirect_uri']
                
                logger.info(f"Connecting to WebSocket (attempt {self.reconnect_attempts + 1})")
                
                async with ws_connect(ws_url, ssl=ssl_context) as websocket:
                    self.websocket = websocket
                    self.running = True
                    self.reconnect_attempts = 0
                    logger.info('WebSocket connected securely')
                    
                    await asyncio.sleep(1)
                    
                    # Subscribe to instruments
                    subscribe_data = {
                        "guid": "trading_system",
                        "method": "sub",
                        "data": {
                            "mode": self.mode,
                            "instrumentKeys": self.instruments
                        }
                    }
                    
                    await websocket.send(json.dumps(subscribe_data).encode('utf-8'))
                    logger.info(f'Subscribed to {len(self.instruments)} instruments in {self.mode} mode')
                    
                    # Heartbeat task
                    heartbeat_task = asyncio.create_task(self._heartbeat())
                    
                    # Main message loop
                    while self.running:
                        try:
                            message = await asyncio.wait_for(
                                websocket.recv(),
                                timeout=30.0
                            )
                            
                            self.last_heartbeat = time.time()
                            decoded_data = self.decode_protobuf(message)
                            
                            if decoded_data and self.on_message_callback:
                                self.on_message_callback(decoded_data)
                        
                        except asyncio.TimeoutError:
                            logger.warning("No data received for 30 seconds")
                            try:
                                pong = await websocket.ping()
                                await asyncio.wait_for(pong, timeout=5.0)
                                logger.info("Ping successful, connection alive")
                            except:
                                logger.error("Ping failed, reconnecting...")
                                break
                        
                        except ConnectionClosed:
                            logger.warning("WebSocket connection closed")
                            break
                    
                    heartbeat_task.cancel()
                    
            except Exception as e:
                logger.error(f"WebSocket error: {e}", exc_info=True)
            
            # Reconnection logic
            if self.running:
                self.reconnect_attempts += 1
                delay = min(self.reconnect_delay * (2 ** self.reconnect_attempts), 300)
                logger.info(f"Reconnecting in {delay} seconds...")
                await asyncio.sleep(delay)
            else:
                logger.info("WebSocket stopped by user")
                break
        
        if self.reconnect_attempts >= self.max_reconnect_attempts:
            logger.critical("Max reconnection attempts reached. Stopping.")
    
    async def _heartbeat(self):
        """Heartbeat to detect stale connections"""
        while self.running:
            await asyncio.sleep(60)
            
            time_since_last = time.time() - self.last_heartbeat
            if time_since_last > 120:
                logger.warning(f"No data received for {time_since_last:.0f} seconds")
    
    def disconnect(self):
        """Stop WebSocket connection"""
        logger.info("Disconnecting WebSocket...")
        self.running = False
    
    def place_order(self, symbol, transaction_type, quantity, price, trigger_price=None):
        """Place order with validation"""
        try:
            # Validate parameters
            errors = self.validate_order_params(symbol, transaction_type, quantity, price)
            if errors:
                logger.error(f"Order validation failed: {errors}")
                return {
                    'status': 'error',
                    'message': f"Validation errors: {', '.join(errors)}"
                }
            
            # FIXED: Use SDK with alias
            api_instance = upstox_sdk.OrderApi(
                upstox_sdk.ApiClient(self.configuration)
            )
            
            body = upstox_sdk.PlaceOrderRequest(
                quantity=quantity,
                product='I',
                validity='DAY',
                price=price,
                tag='algo_trading',
                instrument_token=symbol,
                order_type='LIMIT' if price else 'MARKET',
                transaction_type=transaction_type.upper(),
                disclosed_quantity=0,
                trigger_price=trigger_price if trigger_price else 0,
                is_amo=False
            )
            
            logger.info(f"Placing {transaction_type} order: {symbol} x {quantity} @ {price}")
            api_response = api_instance.place_order(body, api_version='2.0')
            
            logger.info(f"Order placed successfully: {api_response.data.order_id}")
            return {
                'status': 'success',
                'order_id': api_response.data.order_id,
                'message': 'Order placed successfully'
            }
        
        except upstox_sdk.ApiException as e:
            error_msg = f"API error placing order: {e.status} - {e.reason}"
            logger.error(error_msg)
            return {
                'status': 'error',
                'message': error_msg,
                'code': e.status
            }
        
        except Exception as e:
            error_msg = f"Unexpected error placing order: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return {
                'status': 'error',
                'message': error_msg
            }
    
    def get_order_status(self, order_id):
        """Get order status"""
        try:
            api_instance = upstox_sdk.OrderApi(
                upstox_sdk.ApiClient(self.configuration)
            )
            
            response = api_instance.get_order_details(
                order_id=order_id,
                api_version='2.0'
            )
            
            return {
                'status': 'success',
                'order_status': response.data.status,
                'data': response.data
            }
        
        except Exception as e:
            logger.error(f"Error fetching order status: {e}", exc_info=True)
            return {
                'status': 'error',
                'message': str(e)
            }
    
    def cancel_order(self, order_id):
        """Cancel an order"""
        try:
            api_instance = upstox_sdk.OrderApi(
                upstox_sdk.ApiClient(self.configuration)
            )
            
            response = api_instance.cancel_order(
                order_id=order_id,
                api_version='2.0'
            )
            
            logger.info(f"Order cancelled: {order_id}")
            return {
                'status': 'success',
                'message': 'Order cancelled successfully'
            }
        
        except Exception as e:
            logger.error(f"Error cancelling order: {e}", exc_info=True)
            return {
                'status': 'error',
                'message': str(e)
            }


logger.info("Enhanced WebSocket Client Loaded")