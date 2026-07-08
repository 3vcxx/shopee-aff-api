from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List
import requests
import os
import json
import redis
import re

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Redis Connection ──────────────────────────────────────────
REDIS_URL = os.getenv("REDIS_URL")
kv = redis.from_url(REDIS_URL, decode_responses=True) if REDIS_URL else None
ADMIN_KEY = os.getenv("ADMIN_KEY", "123456")

def get_config() -> dict:
    if kv:
        try:
            raw = kv.get("app_config_py")
            if raw:
                return json.loads(raw)
        except Exception:
            pass
    return {}

def set_config(data: dict):
    if kv:
        kv.set("app_config_py", json.dumps(data))

# ── Models ───────────────────────────────────────────────────
class LinkBatch(BaseModel):
    links: List[str]

class SingleLink(BaseModel):
    url: str

# ── Helper Functions ─────────────────────────────────────────
def resolve_shopee_url(url: str) -> str:
    """Hàm giải mã mã link rút gọn s.shopee.vn ngay trên Render"""
    if "s.shopee.vn" in url or "shope.ee" in url:
        try:
            res = requests.get(
                url, 
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}, 
                allow_redirects=False, 
                timeout=10
            )
            if "location" in res.headers:
                return res.headers["location"]
        except Exception:
            pass
    return url

def extract_item_and_shop_id(url: str):
    """Tách lấy ItemID và ShopID từ link dài bản sạch"""
    # Dạng 1: -i.SHOP_ID.ITEM_ID
    match1 = re.search(r'-i\.(\d+)\.(\d+)', url)
    if match1:
        return match1.group(1), match1.group(2)
    
    # Dạng 2: /product/SHOP_ID/ITEM_ID
    match2 = re.search(r'\/product\/(\d+)\/(\d+)', url)
    if match2:
        return match2.group(1), match2.group(2)
        
    return None, None

# ── Routes ───────────────────────────────────────────────────
@app.get("/")
def home():
    return {"message": "Shopee Batch Converter & Commission API is Running!"}

@app.get("/config")
def read_config(key: str = Query("")):
    if key != ADMIN_KEY:
        raise HTTPException(status_code=403, detail="Unauthorized")
    return get_config()

@app.post("/config")
async def write_config(request: Request, key: str = Query(")):
    if key != ADMIN_KEY:
        raise HTTPException(status_code=403, detail="Unauthorized")
    body = await request.json()
    set_config(body)
    return {"success": True, "message": "Đã cập nhật config"}

@app.post("/convert")
def convert_batch(data: LinkBatch):
    links = data.links
    config = get_config()
    
    cookie_entries = config.get("cookies") or config.get("affiliates") or []
    valid_cookies = []
    for entry in cookie_entries:
        ck = entry.get("cookie") or entry.get("id") or ""
        lb = entry.get("label") or "Voucher Shopee"
        ck = ck.replace('"', '').replace("'", "").strip()
        if ck:
            valid_cookies.append({"label": lb, "cookie": ck})

    if not valid_cookies:
        env_cookie = os.getenv("SHOPEE_COOKIE", "").replace('"', '').replace("'", "").strip()
        if env_cookie:
            valid_cookies.append({"label": "Mặc định (Env)", "cookie": env_cookie})

    if not valid_cookies:
        raise HTTPException(status_code=500, detail="Chưa cấu hình Cookie!")

    final_results = [{"original": link, "variants": []} for link in links]

    for vc in valid_cookies:
        payload = {
            "operationName": "batchGetCustomLink",
            "query": "query batchGetCustomLink($linkParams: [CustomLinkParam!], $sourceCaller: SourceCaller) { batchCustomLink(linkParams: $linkParams, sourceCaller: $sourceCaller) { shortLink, failCode } }",
            "variables": {
                "linkParams": [{"originalLink": l} for l in links],
                "sourceCaller": "CUSTOM_LINK_CALLER"
            }
        }
        headers = {
            "content-type": "application/json",
            "cookie": vc["cookie"],
            "user-agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15"
        }

        try:
            response = requests.post(
                "https://affiliate.shopee.vn/api/v3/gql?q=batchCustomLink",
                headers=headers, json=payload, timeout=20
            )
            data_res = response.json()

            if "data" in data_res and "batchCustomLink" in data_res["data"]:
                batch_results = data_res["data"]["batchCustomLink"]
                for idx, item in enumerate(batch_results):
                    short_link = item.get("shortLink")
                    if short_link:
                        final_results[idx]["variants"].append({
                            "label": vc["label"],
                            "url": short_link
                        })
        except Exception:
            continue

    return {"status": "success", "results": final_results}

# ── ENDPOINT MỚI: CHECK HOA HỒNG QUA CỔNG GQL ──────────────────
@app.post("/commission")
def get_commission(data: SingleLink):
    raw_url = data.url
    
    # 1. Đi tìm 1 cookie hợp lệ để chạy mẫu
    config = get_config()
    cookie_entries = config.get("cookies") or config.get("affiliates") or []
    use_cookie = ""
    
    if cookie_entries:
        use_cookie = cookie_entries[0].get("cookie") or cookie_entries[0].get("id") or ""
    if not use_cookie:
        use_cookie = os.getenv("SHOPEE_COOKIE", "")
        
    use_cookie = use_cookie.replace('"', '').replace("'", "").strip()
    if not use_cookie:
        raise HTTPException(status_code=400, detail="Hệ thống chưa có Cookie Shopee để thực hiện request.")

    # 2. Xử lý bóc tách link
    long_url = resolve_shopee_url(raw_url)
    shop_id, item_id = extract_item_and_shop_id(long_url)
    
    # Sử dụng ID để tìm kiếm chính xác qua cổng GQL (tránh truyền URL rác)
    keyword = item_id if item_id else long_url.split('?')[0]

    # 3. Định dạng Payload theo đúng cấu trúc cổng GraphQL của danh sách sản phẩm affiliate
    payload = {
        "operationName": "getProductOfferList",
        "query": """
            query getProductOfferList($request: ProductOfferListRequest) {
                productOfferList(request: $request) {
                    list {
                        itemId
                        shopId
                        itemName
                        imageUrl
                        price
                        commissionRate
                        sellerCommissionRate
                        commission
                    }
                }
            }
        """,
        "variables": {
            "request": {
                "keyword": str(keyword),
                "listType": 0,
                "pageOffset": 0,
                "pageLimit": 1,
                "sortType": 1,
                "clientType": 1
            }
        }
    }

    headers = {
        "content-type": "application/json",
        "cookie": use_cookie,
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    try:
        response = requests.post(
            "https://affiliate.shopee.vn/api/v3/gql?q=getProductOfferList",
            headers=headers, 
            json=payload, 
            timeout=15
        )
        res_data = response.json()
        
        # Kiểm tra cấu trúc dữ liệu trả về từ GraphQL gateway
        if "data" in res_data and "productOfferList" in res_data["data"]:
            p_list = res_data["data"]["productOfferList"].get("list") or []
            if p_list:
                product = p_list[0]
                return {
                    "success": True,
                    "data": {
                        "item_id": product.get("itemId"),
                        "shop_id": product.get("shopId"),
                        "product_name": product.get("itemName"),
                        "image_url": product.get("imageUrl"),
                        "price": product.get("price"),
                        "commission_rate": product.get("commissionRate"),
                        "seller_commission_rate": product.get("sellerCommissionRate") or 0,
                        "estimated_commission": product.get("commission")
                    }
                }
        
        return {
            "success": False,
            "error": "Không tìm thấy thông tin sản phẩm trên hệ thống Affiliate.",
            "shopee_raw": res_data
        }

    except Exception as e:
        return {"success": False, "error": f"Lỗi hệ thống FastAPI: {str(e)}"}
