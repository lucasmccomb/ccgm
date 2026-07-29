import Stripe from 'stripe'

export default {
  async fetch(request, env) {
    const url = new URL(request.url)
    if (url.pathname === '/checkout' && request.method === 'POST') {
      const stripe = new Stripe(env.STRIPE_KEY)
      const cart = await request.json()
      const charge = await stripe.charges.create({ amount: cart.total })
      await env.ORDERS_DB.prepare('INSERT INTO orders (charge_id) VALUES (?)')
        .bind(charge.id)
        .run()
      return Response.json({ ok: true })
    }
    return new Response('not found', { status: 404 })
  },
}
