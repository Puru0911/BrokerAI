/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  devIndicators: {
    position: "bottom-right"
  },

  async rewrites() {
    return [
      {
        source: '/broker/:path*',
        destination: 'http://127.0.0.1:8000/broker/:path*',
      },
    ];
  },
};

module.exports = nextConfig;