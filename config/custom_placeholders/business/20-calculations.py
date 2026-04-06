"""
Example: Calculations using results from previous placeholders
Order: 20 (sees results from unordered placeholders)
"""
from custom_placeholders import placeholder, order

@placeholder
def final_price(context):
    """Calculate final price after discount (no order so highest priority)"""
    amount = float(context.get('$.amount', 0))
    discount = float(context.get('discount', 0))
    return round(amount - discount, 2)

@placeholder
@order(20)
def tier_discount(context):
    """Calculate tier-based discount (order=20, sees final_price)"""
    tier = context.get('customer_tier')
    final = float(context.get('final_price', 0))
    # Apply tier discount on final_price
    if tier == 'GOLD' and final > 500:
        return round(final * 0.05, 2)
    return 0.0

@placeholder
@order(30)
def total_with_tier_discount(context):
    """Final total after all discounts (order=30, sees tier_discount)"""
    final = float(context.get('final_price', 0))
    tier_discount_val = float(context.get('tier_discount', 0))
    return round(final - tier_discount_val, 2)
