def legenda(sh):
    for row in range(sh.nrows - 1, 0, -1):
        for col in range(sh.ncols):
            if "legenda" in str(sh.cell(row, col).value).lower():
                return row
    return None
