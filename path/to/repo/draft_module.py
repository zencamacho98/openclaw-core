class StoppingStateUI:
    def __init__(self):
        self.is_stopping = False
        self.button_style = 'active'

    def update_ui(self, stopping):
        self.is_stopping = stopping
        self.button_style = 'stopping' if self.is_stopping else 'active'

    def get_button_style(self):
        return self.button_style

# Example usage
if __name__ == '__main__':
    ui = StoppingStateUI()
    ui.update_ui(True)
    print(ui.get_button_style())  # Output: stopping
    ui.update_ui(False)
    print(ui.get_button_style())  # Output: active
