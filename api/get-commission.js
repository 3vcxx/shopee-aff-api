export default async function handler(req, res) {
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Access-Control-Allow-Methods', 'GET, OPTIONS');

    if (req.method === 'OPTIONS') return res.status(200).end();

    const { url } = req.query;
    if (!url) {
        return res.status(200).json({ success: false, error: 'Vui lòng cung cấp url sản phẩm' });
    }

    const shopeeCookie = process.env.SHOPEE_COOKIE || '_fbp=fb.1.1768914063092.285491066292534011; SPC_F=o9MRymIb55Jsp1RlBZKMmzG33qTDW8Ok; REC_T_ID=12f9a573-f600-11f0-ba33-5a1ef0ad9851; SPC_CLIENTID=bzlNUnltSWI1NUpzoofuhzpwvuufhpgk; language=vi; SPC_SI=wXYnagAAAABiQlJhcmF5Ob2NGgIAAAAAbTV5U2RCMHg=; SPC_ST=MUtwRHZjMVV6RHlmU05vMdWC9K501Yvu5Mey0GnGCOglSShm5q61G/TbLCkJrnMfz6MPi5Bf7Hjo2EGmuYywyS145nqm2DDsHNSqA1dHrE7lWludZeQtvvsWm4Iej30r1Xk/Q951/NfDe9ACKfbse6Bzc7sQlvjqzdh40Z7N/pFj8eh8LOWGLhBbcu2XIz52GU5bxK53IdpRk2BJ83H54Q==.AAJ7f+x5N4DhvYCJjKgkQ9pdxyCE3s4CuJTKCtHE5kcS; SPC_U=283824214; SPC_R_T_ID=D0grqBovtIOM/JYLaFoK3KUdwx04XxnuKS1nU3xhDwl5jrVkfxXpgHIb8KPEBbA//vuzXST9buQ08t3xkp3k3TkP19bgsXF9BSAHu407iuOLuyxv+fX6pXiqqE44zEnQU8r5WMtoJ/rPqmauwc4bnQfggTVAvxpfeUegLRmCuCY=; SPC_R_T_IV=b21XU2ZURnNJbjlZWFpsbw==; SPC_T_ID=D0grqBovtIOM/JYLaFoK3KUdwx04XxnuKS1nU3xhDwl5jrVkfxXpgHIb8KPEBbA//vuzXST9buQ08t3xkp3k3TkP19bgsXF9BSAHu407iuOLuyxv+fX6pXiqqE44zEnQU8r5WMtoJ/rPqmauwc4bnQfggTVAvxpfeUegLRmCuCY=; SPC_T_IV=b21XU2ZURnNJbjlZWFpsbw==; _med=affiliates;';

    try {
        // Chuẩn hóa link: Loại bỏ toàn bộ tracking rác sau dấu chấm hỏi (?) để Shopee tìm kiếm chính xác nhất
        const cleanUrl = url.split('?')[0];
        const encodedKeyword = encodeURIComponent(cleanUrl);

        // Gọi API danh sách sản phẩm với từ khóa là link sạch đã được định dạng
        const apiUrl = `https://affiliate.shopee.vn/api/v3/offer/product/list?list_type=0&sort_type=1&page_offset=0&page_limit=1&client_type=1&keyword=${encodedKeyword}`;

        const shopeeResponse = await fetch(apiUrl, {
            method: 'GET',
            headers: {
                'Cookie': shopeeCookie,
                'Accept': 'application/json, text/plain, */*',
                'Accept-Language': 'vi-VN,vi;q=0.9',
                'Referer': 'https://affiliate.shopee.vn/offer/product_offer',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36'
            }
        });

        const data = await shopeeResponse.json();

        // Trường hợp thành công mỹ mãn
        if (data.code === 20000 && data.data && data.data.list && data.data.list.length > 0) {
            const product = data.data.list[0];
            return res.status(200).json({
                success: true,
                data: {
                    item_id: product.item_id,
                    shop_id: product.shop_id,
                    product_name: product.item_name,
                    image_url: product.image_url,
                    price: product.price,
                    commission_rate: product.commission_rate,
                    seller_commission_rate: product.seller_commission_rate || 0,
                    estimated_commission: product.commission
                }
            });
        } 
        
        // Trường hợp API chạy được nhưng trống data hoặc lỗi phân quyền / anti-cheat của Shopee
        return res.status(200).json({
            success: false,
            error: data.data && data.data.list && data.data.list.length === 0 
                ? 'Shopee không tìm thấy sản phẩm này trong danh mục Affiliate.' 
                : `Shopee trả về mã lỗi hệ thống: ${data.code}`,
            shopee_raw: data // Đẩy toàn bộ cục JSON của Shopee về PHP hiển thị để xem lỗi gì
        });

    } catch (error) {
        return res.status(200).json({ success: false, error: 'Lỗi thực thi code tại Vercel: ' + error.message });
    }
}
