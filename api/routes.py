def paginate_results(results, page=1, per_page=20):
    total = len(results)
    start = (page - 1) * per_page
    end = start + per_page

    return {
        'results': results[start:end],
        'page': page,
        'per_page': per_page,
        'total': total,
        'total_pages': (total + per_page - 1) // per_page
    }
