from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests
import os
import re
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ProductRequest(BaseModel):
    url: str

def resolve_shopee_url(url: str) -> str:
    """Giải mã link ngắn s.shopee.vn thành link dài"""
    if "s.shopee.vn" in url or "shope.ee" in url:
        try:
            res = requests.get(url, allow_redirects=False, timeout=10)
            if "location" in res.headers:
                return res.headers["location"]
        except Exception:
            pass
    return url

def extract_item_id(url: str) -> str:
    """Tách lấy Item ID từ link sản phẩm để làm từ khóa tìm kiếm chuẩn nhất"""
    match = re.search(r'-i\.(\d+)\.(\d+)', url)
    if match:
        return match.group(2)
    match2 = re.search(r'\/product\/(\d+)\/(\d+)', url)
    if match2:
        return match2.group(2)
    # Nếu không tách được ID, lấy phần link trước dấu ?
    return url.split('?')[0]

@app.get("/")
def home():
    return {"message": "API Check Hoa Hồng Shopee đang chạy!"}

@app.post("/check-product")
def check_product(data: ProductRequest):
    # 1. Bốc cookie an toàn từ biến môi trường
    cookie = os.getenv("SHOPEE_COOKIE", "").replace('"', '').replace("'", "").strip()
    if not cookie:
        raise HTTPException(status_code=500, detail="Chưa cấu hình SHOPEE_COOKIE trên server!")

    # 2. Xử lý Link đầu vào
    long_url = resolve_shopee_url(data.url)
    keyword = extract_item_id(long_url)

    headers = {
        "Cookie": cookie
    }

    # 3. Gọi API 1: Lấy hoa hồng Shopee (list_type=0)
    url_shopee = f"https://affiliate.shopee.vn/api/v3/offer/product/list?list_type=0&sort_type=1&page_offset=0&page_limit=1&client_type=1&keyword={keyword}"
    
    # 4. Gọi API 2: Lấy hoa hồng Xtra / Người bán (list_type=7)
    url_xtra = f"https://affiliate.shopee.vn/api/v3/offer/product/list?list_type=7&sort_type=1&page_offset=0&page_limit=1&client_type=1&keyword={keyword}"

    product_data = {
        "name": "Không tìm thấy sản phẩm",
        "image": "",
        "price": 0,
        "shopee_commission_rate": 0,
        "shopee_commission_value": 0,
        "xtra_commission_rate": 0,
        "xtra_commission_value": 0,
        "total_commission": 0
    }

    try:
        # Bắn API Shopee thường
        res_shopee = requests.get(url_shopee, headers=headers, timeout=15).json()
        if "data" in res_shopee and res_shopee["data"].get("list"):
            p = res_shopee["data"]["list"][0]
            product_data["name"] = p.get("item_name")
            product_data["image"] = p.get("image_url")
            product_data["price"] = p.get("price", 0)
            product_data["shopee_commission_rate"] = p.get("commission_rate", 0)
            product_data["shopee_commission_value"] = p.get("commission", 0)

        # Bắn API Xtra
        res_xtra = requests.get(url_xtra, headers=headers, timeout=15).json()
        if "data" in res_xtra and res_xtra["data"].get("list"):
            p_xtra = res_xtra["data"]["list"][0]
            product_data["xtra_commission_rate"] = p_xtra.get("commission_rate", 0)
            product_data["xtra_commission_value"] = p_xtra.get("commission", 0)

        # Tính tổng hoa hồng thực nhận
        product_data["total_commission"] = product_data["shopee_commission_value"] + product_data["xtra_commission_value"]

        return {"success": True, "product": product_data}

    except Exception as e:
        return {"success": False, "error": str(e)}
