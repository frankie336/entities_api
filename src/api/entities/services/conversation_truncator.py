from transformers import AutoTokenizer


class ConversationTruncator:
    """
    Service class to truncate a conversation dialogue list so that the total token count
    does not exceed a specified percentage of the model's max context window.

    System messages (role == 'system') are never removed. Additionally, after truncation,
    consecutive messages from the same role are merged to maintain an alternating dialogue.

    Attributes:
        max_context_window (int): Maximum token count the model supports (e.g., 4096).
        threshold_percentage (float): Fraction (0-1) of max_context_window to trigger truncation.
        tokenizer (AutoTokenizer): Hugging Face tokenizer instance.
    """

    def __init__(self, model_name, max_context_window, threshold_percentage):
        self.max_context_window = max_context_window
        self.threshold_percentage = threshold_percentage  # e.g., 0.8 for 80%

        # Load the Hugging Face tokenizer for the given model
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)

    def count_tokens(self, text):
        """Uses the Hugging Face tokenizer to count tokens in a given text."""
        if not text:
            return 0
        return len(self.tokenizer.encode(text, add_special_tokens=False))

    def truncate(self, conversation):
        """
        Truncate the conversation dialogue (excluding system messages) if the total token count
        exceeds the threshold. Then, merge consecutive messages from the same role.

        Parameters:
            conversation (list): List of message dictionaries (each with 'role' and 'content').

        Returns:
            list: The truncated and merged conversation.
        """
        # Separate system messages (always kept) and other messages.
        system_messages = [msg for msg in conversation if msg.get('role') == 'system']
        other_messages = [msg for msg in conversation if msg.get('role') != 'system']

        # Count tokens for system and non-system messages.
        system_token_count = sum(self.count_tokens(msg.get('content', '')) for msg in system_messages)
        other_token_count = sum(self.count_tokens(msg.get('content', '')) for msg in other_messages)
        total_tokens = system_token_count + other_token_count

        # Determine the threshold token count.
        threshold_tokens = self.max_context_window * self.threshold_percentage

        # If the total token count is below the threshold, no truncation is needed.
        if total_tokens <= threshold_tokens:
            return self.merge_consecutive_messages(conversation)

        # Calculate the optimal token budget for non-system messages.
        optimal_other_tokens = threshold_tokens - system_token_count

        # Remove older non-system messages until token count fits within optimal budget.
        truncated_other_messages = other_messages.copy()
        while truncated_other_messages and other_token_count > optimal_other_tokens:
            removed_msg = truncated_other_messages.pop(0)
            other_token_count -= self.count_tokens(removed_msg.get('content', ''))

        # Recombine system messages and the truncated non-system messages,
        # preserving their original order.
        truncated = system_messages + truncated_other_messages
        truncated.sort(key=lambda m: conversation.index(m))

        # Finally, merge consecutive messages from the same role.
        truncated = self.merge_consecutive_messages(truncated)
        return truncated

    def merge_consecutive_messages(self, conversation):
        """
        Merges consecutive messages from the same role by concatenating their content.

        Parameters:
            conversation (list): List of message dictionaries.

        Returns:
            list: A new conversation list with consecutive same-role messages merged.
        """
        if not conversation:
            return conversation

        merged = [conversation[0]]
        for msg in conversation[1:]:
            last_msg = merged[-1]
            if msg.get('role') == last_msg.get('role'):
                # Merge by concatenating content with a newline separator.
                last_msg['content'] = f"{last_msg.get('content', '')}\n{msg.get('content', '')}"
            else:
                merged.append(msg)
        return merged
