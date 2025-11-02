import asyncio
import json
import ssl
import requests
from google.protobuf.json_format import MessageToDict
import MarketDataFeedV3_pb2 as pb
import upstox_client
from websockets.asyncio.client import connect as ws_connect


class UpstoxWebSocketClient:
    def __init__(self, access_token, instruments, mode='full_d30', on_message_callback=None):
        self.access_token = access_token
        self.instruments = instruments
        self.mode = mode
        self.on_message_callback = on_message_callback
        self.websocket = None
        self.running = False
        
        self.configuration = upstox_client.Configuration()
        self.configuration.access_token = access_token
    
    def get_market_feed_authorization(self):
        headers = {
            'Accept': 'application/json',
            'Authorization': f'Bearer {self.access_token}'
        }
        url = 'https://api.upstox.com/v3/feed/market-data-feed/authorize'
        response = requests.get(url=url, headers=headers)
        return response.json()
    
    def decode_protobuf(self, buffer):
        feed_response = pb.FeedResponse()
        feed_response.ParseFromString(buffer)
        return MessageToDict(feed_response)
    
    def connect(self):
        asyncio.run(self._async_connect())
    
    async def _async_connect(self):
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        
        auth_response = self.get_market_feed_authorization()
        ws_url = auth_response['data']['authorized_redirect_uri']
        
        async with ws_connect(ws_url, ssl=ssl_context) as websocket:
            self.websocket = websocket
            self.running = True
            print('✅ WebSocket connected')
            
            await asyncio.sleep(1)
            
            subscribe_data = {
                "guid": "trading_system",
                "method": "sub",
                "data": {
                    "mode": self.mode,
                    "instrumentKeys": self.instruments
                }
            }
            
            await websocket.send(json.dumps(subscribe_data).encode('utf-8'))
            print(f'📡 Subscribed: {self.instruments}')
            
            while self.running:
                try:
                    message = await websocket.recv()
                    decoded_data = self.decode_protobuf(message)
                    
                    if self.on_message_callback:
                        self.on_message_callback(decoded_data)
                
                except Exception as e:
                    print(f'Error: {e}')
                    if not self.running:
                        break
                    await asyncio.sleep(5)
    
    def disconnect(self):
        self.running = False
        if self.websocket:
            asyncio.run(self.websocket.close())
    
    def place_order(self, symbol, transaction_type, quantity, price, trigger_price=None):
        try:
            api_instance = upstox_client.OrderApi(
                upstox_client.ApiClient(self.configuration)
            )
            
            body = upstox_client.PlaceOrderRequest(
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
            
            api_response = api_instance.place_order(body, api_version='2.0')
            
            return {
                'status': 'success',
                'order_id': api_response.data.order_id
            }
        
        except Exception as e:
            return {
                'status': 'error',
                'message': str(e)
            }