export default async function handler(req, res) {
    // Kích hoạt CORS để PHP trên hosting có thể gọi được
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Access-Control-Allow-Methods', 'GET, OPTIONS');

    if (req.method === 'OPTIONS') {
        return res.status(200).end();
    }

    const { url } = req.query;

    if (!url) {
        return res.status(400).json({ error: 'Vui lòng cung cấp link sản phẩm (url)' });
    }

    // Cookie Shopee - CỰC KỲ QUAN TRỌNG: Nên cấu hình trong Environment Variables của Vercel
    const shopeeCookie = process.env.SHOPEE_COOKIE || 'DÁN_COOKIE_CỦA_BẠN_VÀO_ĐÂY_NẾU_KHÔNG_DÙNG_ENV';

    try {
        // Encode URL sản phẩm để truyền vào biến keyword
        const encodedKeyword = encodeURIComponent(url);
        
        // Gọi API list_type=0 để tìm sản phẩm theo link
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

        // Kiểm tra xem có tìm thấy sản phẩm không
        if (data.code === 20000 && data.data && data.data.list && data.data.list.length > 0) {
            const product = data.data.list[0];

            // Bóc tách dữ liệu trả về (tên biến có thể thay đổi nhẹ tùy theo response thực tế của Shopee)
            const result = {
                item_id: product.item_id,
                shop_id: product.shop_id,
                product_name: product.item_name,
                image_url: product.image_url,
                price: product.price, // Giá bán
                commission_rate: product.commission_rate, // % Hoa hồng cơ bản
                seller_commission_rate: product.seller_commission_rate || 0, // % Hoa hồng Xtra/Người bán
                estimated_commission: product.commission, // Hoa hồng ước tính (VNĐ)
            };

            return res.status(200).json({ success: true, data: result });
        } else {
            return res.status(404).json({ success: false, error: 'Không tìm thấy thông tin hoa hồng cho link này.' });
        }

    } catch (error) {
        return res.status(500).json({ success: false, error: error.message });
    }
}
