from colorama import Fore
from colorama import Style

from pydantic.v1 import BaseModel, Field
from typing import Union, List, Literal, Tuple
from semantic_router.splitters.consecutive_sim import ConsecutiveSimSplitter
from semantic_router.splitters.cumulative_sim import CumulativeSimSplitter
from semantic_router.encoders import BaseEncoder
from semantic_router.schema import Message
from semantic_router.schema import DocumentSplit

# Define a type alias for the splitter to simplify the annotation
SplitterType = Union[ConsecutiveSimSplitter, CumulativeSimSplitter, None]

colors = [
    Fore.WHITE,
    Fore.RED,
    Fore.GREEN,
    Fore.YELLOW,
    Fore.BLUE,
    Fore.MAGENTA,
    Fore.CYAN,
]


class Conversation(BaseModel):
    messages: List[Message] = Field(
        default_factory=list
    )  # Ensure this is initialized as an empty list
    topics: List[Tuple[int, str]] = []
    splitter: SplitterType = None

    def __str__(self):
        if not self.messages:
            return ""
        if not self.topics:
            return "\n".join([str(message) for message in self.messages])
        else:
            # we print each topic a different color
            return_str_list = []
            current_topic_id = None
            color_idx = 0
            for topic_id, message in self.topics:
                if topic_id != current_topic_id:
                    # change color
                    color_idx = (color_idx + 1) % len(colors)
                    current_topic_id = topic_id
                return_str_list.append(f"{colors[color_idx]}{message}{Style.RESET_ALL}")
            return "\n".join(return_str_list)

    def add_new_messages(self, new_messages: List[Message]):
        """Adds new messages to the conversation.

        :param messages: The new messages to be added to the conversation.
        :type messages: List[Message]
        """
        self.messages.extend(new_messages)

    def remove_topics(self):
        self.topics = []

    def configure_splitter(
        self,
        encoder: BaseEncoder,
        threshold: float = 0.5,
        split_method: Literal[
            "consecutive_similarity", "cumulative_similarity"
        ] = "consecutive_similarity",
    ):
        """
        Configures the splitter for the conversation based on the specified method.

        This method sets the splitter attribute of the Conversation class to an instance of the appropriate splitter class, based on the `split_method` parameter. It uses the provided encoder and similarity threshold to initialize the splitter.

        :param encoder: The encoder to be used by the splitter for encoding messages.
        :type encoder: BaseEncoder
        :param threshold: The similarity threshold to be used by the splitter. Defaults to 0.5.
        :type threshold: float
        :param split_method: The method to be used for splitting the conversation into topics. Can be one of "consecutive_similarity" or "cumulative_similarity". Defaults to "consecutive_similarity".
        :type split_method: Literal["consecutive_similarity", "cumulative_similarity"]
        :raises ValueError: If an invalid split method is provided.
        """

        if split_method == "consecutive_similarity":
            self.splitter = ConsecutiveSimSplitter(
                encoder=encoder, score_threshold=threshold
            )
        elif split_method == "cumulative_similarity":
            self.splitter = CumulativeSimSplitter(
                encoder=encoder, score_threshold=threshold
            )
        else:
            raise ValueError(f"Invalid split method: {split_method}")

    def get_last_message_and_topic_id(self):
        """
        Retrieves the last message and its corresponding topic ID from the list of topics.

        This method scans the list of topics, if any, and returns the topic ID and message of the last entry. If there are no topics, it returns None for both the topic ID and message.

        The last message from a previous spiltting is useful because it can be passed to the splitter along with new messages, and if the first new message is assigned the same topic as the last message, then we know that the new message should continue with the same topic ID as the last message.

        :return: A tuple containing the topic ID (int) and message (str) of the last topic, or (None, None) if there are no topics.
        :rtype: tuple[int | None, str | None]
        """

        if self.topics:
            return self.topics[-1]
        else:
            return None, None

    def determine_topic_start_index(self, new_topics, last_topic_id, last_message):
        """
        Determines the starting index for new topics based on existing topics and the last message.

        :param new_topics: The list of new topics generated by the splitter.
        :type new_topics: List[DocumentSplit]
        :param last_topic_id: The topic ID of the last message from the previous splitting.
        :type last_topic_id: int, optional
        :param last_message: The last message from the previous splitting.
        :type last_message: str, optional
        :return: The starting index for new topics.
        :rtype: int
        """
        if not self.topics or not new_topics:
            return 1
        if (
            last_topic_id is not None
            and last_message
            and last_message in new_topics[0].docs
        ):
            return last_topic_id
        return self.topics[-1][0] + 1

    def append_new_topics(self, new_topics, start) -> None:
        """
        Appends new topics to the list of topics with unique IDs.

        This method takes a list of new topics generated by the splitter and appends them to the existing list of topics, ensuring each topic is assigned a unique ID starting from the specified starting index.

        :param new_topics: The list of new topics generated by the splitter.
        :type new_topics: List[DocumentSplit]
        :param start: The starting index for new topics.
        :type start: int
        """
        for i, topic in enumerate(new_topics, start=start):
            for message in topic.docs:
                self.topics.append((i, message))

    def split_by_topic(
        self, force: bool = False
    ) -> Tuple[List[Tuple[int, str]], List[DocumentSplit]]:
        """
        Splits the messages into topics based on their semantic similarity.

        This method processes unclustered messages, splits them into topics using the configured splitter, and appends the new topics to the existing list of topics with unique IDs. It ensures that messages belonging to the same topic are grouped together, even if they were not processed in the same batch.

        :raises ValueError: If the splitter is not configured before calling this method.

        :return: A tuple containing the updated list of topics and the list of new topics generated in this call.
        :rtype: tuple[list[tuple[int, str]], list[DocumentSplit]]
        """

        if self.splitter is None:
            raise ValueError(
                "Splitter is not configured. Please call configure_splitter first."
            )
        new_topics: List[DocumentSplit] = []

        if self.topics:
            # reset self.topics
            self.topics = []

        # Get unclusteed messages.
        unclustered_messages = self.messages[len(self.topics) :]
        if not unclustered_messages:
            print("No unclustered messages to process.")
            return self.topics, new_topics

        # Extract the last topic ID and message from the previous splitting, if they exist.
        last_topic_id, last_message = self.get_last_message_and_topic_id()

        # Initialize docs with the last message from the last topic if it exists, and with unclustered messages.
        # TODO: Currenlty only getting last message from last topic in previous splitting. Should we get more for more reliable continuation of topic ids?
        docs = [last_message] if last_message else []
        docs.extend([f"{m.role}: {m.content}" for m in unclustered_messages])

        new_topics = self.splitter(docs)

        # Ensure there are new topics before proceeding
        if not new_topics:
            return self.topics, []

        # If last_message and the first new message are assigned the same topic ID, then we know the new message should take last_message's place original topic id.
        start = self.determine_topic_start_index(
            new_topics, last_topic_id, last_message
        )

        # If the last message from the previous splitting is found in the first new topic, remove it
        if self.topics and new_topics[0].docs[0] == self.topics[-1][1]:
            new_topics[0].docs.pop(0)

        self.append_new_topics(new_topics, start)

        # TODO: Instead of self.topics as list of tuples should it also be a list of DocumentSplit objects?
        return self.topics, new_topics
