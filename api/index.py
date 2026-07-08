import os
import json
import re
from typing import List
from urllib.parse import urlparse, parse_qs

import requests
import redis
from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

# ── Nạp Biến Môi Trường ───────────────────────────────────────
load_dotenv()

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

# QUAN TRỌNG: không đặt giá trị mặc định cho ADMIN_KEY nữa (trước là "123456").
# Thiếu biến môi trường -> khoá cứng endpoint quản trị thay vì lộ mật khẩu ai cũng đoán ra.
ADMIN_KEY = os.getenv("ADMIN_KEY")


def _check_admin(key: str):
    if not ADMIN_KEY:
        raise HTTPException(
            status_code=500,
            detail="Server chưa cấu hình ADMIN_KEY, endpoint quản trị đang bị khoá vì lý do an toàn."
        )
    if key != ADMIN_KEY:
        raise HTTPException(status_code=403, detail="Unauthorized")


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
# Trước chỉ có "s.shopee.vn" và "shope.ee" -> "vn.shp.ee" (ví dụ bạn đưa) không khớp domain nào cả
SHOPEE_SHORT_DOMAINS = ("s.shopee.vn", "shope.ee", "shp.ee")


def resolve_shopee_url(url: str, max_hops: int = 5) -> str:
    """Giải mã link rút gọn (s.shopee.vn / shope.ee / *.shp.ee, vd vn.shp.ee)
    thành link gốc dài. Theo tối đa max_hops lần redirect thay vì chỉ 1 lần."""
    current = url
    for _ in range(max_hops):
        if not any(d in current for d in SHOPEE_SHORT_DOMAINS):
            break
        try:
            res = requests.get(
                current,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
                allow_redirects=False,
                timeout=10
            )
            location = res.headers.get("location")
            if not location:
                break
            current = location
        except Exception:
            break
    return current


def extract_item_and_shop_id(url: str):
    """Bóc tách ShopID và ItemID từ URL sản phẩm"""
    match1 = re.search(r'-i\.(\d+)\.(\d+)', url)
    if match1:
        return match1.group(1), match1.group(2)

    match2 = re.search(r'/product/(\d+)/(\d+)', url)
    if match2:
        return match2.group(1), match2.group(2)

    # Dạng 3: query string ?shopid=...&itemid=...
    qs = parse_qs(urlparse(url).query)
    if "shopid" in qs and "itemid" in qs:
        return qs["shopid"][0], qs["itemid"][0]

    return None, None


# ── Routes ───────────────────────────────────────────────────
@app.get("/")
def home():
    return {"message": "Shopee Affiliate GraphQL API is Running Successfully!"}


@app.get("/config")
def read_config(key: str = Query("")):
    _check_admin(key)
    return get_config()


@app.post("/config")
async def write_config(request: Request, key: str = Query("")):
    _check_admin(key)
    body = await request.json()
    set_config(body)
    return {"success": True, "message": "Đã cập nhật config thành công"}


# ── ENDPOINT 1: RÚT GỌN LINK BATCH (giữ nguyên logic gốc) ─────
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
        raise HTTPException(status_code=500, detail="Hệ thống chưa cấu hình Cookie Shopee!")

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


# ── ENDPOINT 2: CHECK HOA HỒNG QUA GQL ────────────────────────
@app.post("/commission")
def get_commission(data: SingleLink):
    raw_url = data.url

    config = get_config()
    cookie_entries = config.get("cookies") or config.get("affiliates") or []

    candidate_cookies = []
    for entry in cookie_entries:
        ck = (entry.get("cookie") or entry.get("id") or "").replace('"', '').replace("'", "").strip()
        if ck:
            candidate_cookies.append(ck)

    if not candidate_cookies:
        env_cookie = os.getenv("SHOPEE_COOKIE", "").replace('"', '').replace("'", "").strip()
        if env_cookie:
            candidate_cookies.append(env_cookie)

    if not candidate_cookies:
        raise HTTPException(status_code=400, detail="Hệ thống chưa cấu hình Cookie Shopee!")

    # 1. Giải mã link ngắn (giờ đã nhận thêm vn.shp.ee) + tách item/shop id
    long_url = resolve_shopee_url(raw_url)
    shop_id, item_id = extract_item_and_shop_id(long_url)
    keyword = item_id if item_id else long_url.split('?')[0]

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
                "pageLimit": 20,   # lấy nhiều hơn 1 để có cái đối chiếu itemId
                "sortType": 1,
                "clientType": 1
            }
        }
    }

    last_raw = None

    # 2. Thử lần lượt từng cookie cho tới khi tìm đúng sản phẩm (thay vì chỉ dùng cookie đầu)
    for cookie in candidate_cookies:
        headers = {
            "content-type": "application/json",
            "cookie": cookie,
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
            last_raw = res_data
        except Exception as e:
            last_raw = {"error": str(e)}
            continue

        p_list = ((res_data.get("data") or {}).get("productOfferList") or {}).get("list") or []

        # 3. Đối chiếu đúng itemId thay vì tin mù kết quả đầu tiên trả về
        match = None
        if item_id:
            match = next((p for p in p_list if str(p.get("itemId")) == str(item_id)), None)
        elif p_list:
            match = p_list[0]

        if match:
            return {
                "success": True,
                "data": {
                    "item_id": match.get("itemId"),
                    "shop_id": match.get("shopId"),
                    "product_name": match.get("itemName"),
                    "image_url": match.get("imageUrl"),
                    "price": match.get("price"),
                    "commission_rate": match.get("commissionRate"),
                    "seller_commission_rate": match.get("sellerCommissionRate") or 0,
                    "estimated_commission": match.get("commission")
                }
            }
        # cookie này gọi được nhưng không thấy đúng sản phẩm -> thử cookie kế tiếp nếu còn

    return {
        "success": False,
        "error": "Không tìm thấy đúng sản phẩm (itemId không khớp) trên hệ thống Affiliate.",
        "shopee_raw": last_raw
    }
