def get_lot_size_filters(symbol):
    return {
        "minQty": 1,
        "stepSize": 1
    }

def round_step_size(value, step_size):
    return round(value // step_size * step_size, 8)
