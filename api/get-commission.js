export default async function handler(req, res) {
    // Kích hoạt CORS
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Access-Control-Allow-Methods', 'GET, OPTIONS');

    if (req.method === 'OPTIONS') {
        return res.status(200).end();
    }

    const { url } = req.query;

    if (!url) {
        return res.status(200).json({ success: false, error: 'Vui lòng cung cấp link sản phẩm (url)' });
    }

    const shopeeCookie = process.env.SHOPEE_COOKIE || 'DÁN_COOKIE_CỦA_BẠN_VÀO_ĐÂY_NẾU_KHÔNG_DÙNG_ENV';

    try {
        let targetUrl = url;

        // BƯỚC 1: Tự động giải mã nếu người dùng nhập link rút gọn (s.shopee.vn hoặc shope.ee)
        if (url.includes('s.shopee.vn') || url.includes('shope.ee')) {
            const resolveRes = await fetch(url, {
                method: 'GET',
                redirect: 'follow', // Tự động đi theo đường link redirect để lấy link gốc
                headers: {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                }
            });
            targetUrl = resolveRes.url; // Đây là link Shopee dài sau khi giải mã
        }

        // BƯỚC 2: Tách lấy ID sản phẩm (Item ID) từ link dài để đảm bảo API Shopee tìm chính xác nhất
        let keyword = targetUrl;
        const matchI = targetUrl.match(/-i\.(\d+)\.(\d+)/);
        if (matchI) {
            keyword = matchI[2]; // Lấy ItemID từ dạng -i.SHOPID.ITEMID
        } else {
            const matchProduct = targetUrl.match(/\/product\/(\d+)\/(\d+)/);
            if (matchProduct) {
                keyword = matchProduct[2]; // Lấy ItemID từ dạng /product/SHOPID/ITEMID
            }
        }

        // BƯỚC 3: Gọi API Shopee với keyword đã được tối ưu (ID sản phẩm hoặc link sạch)
        const encodedKeyword = encodeURIComponent(keyword);
        const apiUrl = `https://affiliate.shopee.vn/api/v3/offer/product/list?list_type=0&sort_type=1&page_offset=0&page_limit=1&client_type=1&keyword=${encodedKeyword}`;

        const shopeeResponse = await fetch(apiUrl, {
            method: 'GET',
            headers: {
                'Cookie': shopeeCookie,
                'Content-Type': 'application/json',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }
        });

        const data = await shopeeResponse.json();

        // BƯỚC 4: Trả kết quả về cho PHP (Luôn dùng status 200 để PHP không bị lỗi bóc tách)
        if (data.code === 20000 && data.data && data.data.list && data.data.list.length > 0) {
            const product = data.data.list[0];

            const result = {
                item_id: product.item_id,
                shop_id: product.shop_id,
                product_name: product.item_name,
                image_url: product.image_url,
                price: product.price, 
                commission_rate: product.commission_rate, 
                seller_commission_rate: product.seller_commission_rate || 0, 
                estimated_commission: product.commission, 
            };

            return res.status(200).json({ success: true, data: result });
        } else {
            return res.status(200).json({ 
                success: false, 
                error: 'Không tìm thấy thông tin sản phẩm. Có thể sản phẩm này không nằm trong chương trình tiếp thị liên kết hoặc Cookie của bạn đã hết hạn.' 
            });
        }

    } catch (error) {
        return res.status(200).json({ success: false, error: 'Lỗi hệ thống API: ' + error.message });
    }
}
