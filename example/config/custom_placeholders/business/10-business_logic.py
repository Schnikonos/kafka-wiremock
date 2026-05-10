"""
Example: Basic business logic placeholders (unordered - executed first)
"""
def calculate_discount(context):
    """Calculate discount based on amount"""
    try:
        amount = float(context.get('$.amount', 0))
        if amount > 1000:
            return round(amount * 0.1, 2)
        return 0.0
    except (ValueError, TypeError):
        return 0.0
def get_customer_tier(context):
    """Get customer tier based on customer ID"""
    customer_id = context.get('$.customerId')
    if not customer_id:
        return 'STANDARD'
    # Simple logic - in reality would lookup from database
    return 'GOLD' if customer_id.startswith('VIP') else 'STANDARD'
# Expose as placeholders
PLACEHOLDERS = {
    'discount': calculate_discount,
    'customer_tier': get_customer_tier,
}
