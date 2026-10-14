class EnvelopeDetector:
    def __init__(self, buffer_size=64):
        self.buffer_size = buffer_size
        self.circular_buffer = [0] * buffer_size
        self.data_index = 0
        self.sum = 0

    def get_envelope(self, abs_emg):
        self.sum -= self.circular_buffer[self.data_index]
        self.sum += abs_emg

        self.circular_buffer[self.data_index] = abs_emg
        self.data_index = (self.data_index + 1) % self.buffer_size

        return (self.sum / self.buffer_size) * 2